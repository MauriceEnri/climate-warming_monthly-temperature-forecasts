#!/usr/bin/env python3

"""
update_dwd_current.py

Incrementally update the current month's DWD station data, lapse rate,
and daily raster means.

Workflow
--------
1. Load existing monthly lapse-rate file
2. Download daily/kl/recent/ -> previous day
3. Download 10_minutes/air_temperature/now/ -> current day
4. Load persistent current-month station data
5. Replace/update previous-day and current-day station observations
6. Recalculate current-month lapse-rate regression
7. Update monthly_lapse_rates_2026.txt
8. Calculate previous-day raster using updated slope
9. Calculate current-day raster using updated slope
10. Load existing daily raster file
11. Replace previous-day and current-day rows
12. Save updated daily raster file
"""

import io
import os
import zipfile
from pathlib import Path
import time
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from scipy.spatial import cKDTree
from pyproj import Transformer
import argparse

HEARTBEAT_FILE = Path(
    os.environ.get(
        "DWD_HEARTBEAT",
        "dwd_progress.txt",
    )
)
def reset_heartbeat():
    """
    Remove any heartbeat from a previous run and create
    a fresh heartbeat for this run.
    """

    HEARTBEAT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        HEARTBEAT_FILE.unlink()
    except FileNotFoundError:
        pass

    HEARTBEAT_FILE.touch()

def update_heartbeat():
    """
    Update the DWD progress heartbeat file.

    The shell watchdog uses the modification time of this file
    to determine whether the Python process is still making progress.
    """

    HEARTBEAT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    HEARTBEAT_FILE.touch()

# =============================================================================
# CONFIGURATIONMONTHLY_RASTER_FILE
# =============================================================================
BASE_DIR = Path(
    "/mnt/c/Users/user/Documents/projects_stuff/climate_change"
)
YEAR = 2026

# DWD endpoints
DWD_BASE_URL = (
    "https://opendata.dwd.de/climate_environment/"
    "CDC/observations_germany/climate/"
)

RECENT_URL = DWD_BASE_URL + "10_minutes/air_temperature/recent/"
NOW_URL = DWD_BASE_URL + "10_minutes/air_temperature/now/"

# Persistent station data
CURRENT_STATION_DIR = BASE_DIR / "DWD_raster_means" / "current_station_data"
CURRENT_STATION_DIR.mkdir(parents=True, exist_ok=True)

# Lapse-rate file
LAPSE_RATE_DIR = BASE_DIR / "forecast_rastered" / "data" / "lapse_rates"
LAPSE_RATE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)
LAPSE_RATE_FILE = (
    LAPSE_RATE_DIR
    / f"monthly_lapse_rates_{YEAR}.txt"
)
# Existing daily raster file
STORE_DIR = BASE_DIR / "forecast_rastered" / "data" / "current_monthly_means"
#parameters for temperature rastering
K = 25
MAX_DIST = 120000.0
REPROJECTION = "EPSG:3035"
#daily and monthly rastered files and official DWD monthly temperatures
DAILY_RASTER_FILE = (
    STORE_DIR
    / f"DWD_daily_raster_sta{K}_dist{MAX_DIST:.3f}_"
      f"{REPROJECTION}_{YEAR}-{YEAR + 1}.txt"
)
OFFICIAL_MONTHLY_FILE = (
    BASE_DIR / "complete_timeseries_temperature_germany.csv"
)
MONTHLY_RASTER_FILE = (
    BASE_DIR
    / "forecast_rastered"
    / "data"
    / "current_monthly_means"
    / (
        f"DWD_monthly_raster_sta{K}_"
        f"dist{MAX_DIST:.3f}_"
        f"{REPROJECTION}_"
        f"{YEAR}-{YEAR + 1}.txt"
    )
)
# Existing static grid
STATIC_GRID_FILE = (
    BASE_DIR
    / "forecast_rastered"
    / "data"
    / "static"
    / "Germany_static_grid.npz"
)
#Ensure directories exist
STORE_DIR.mkdir(parents=True, exist_ok=True)
MONTHLY_RASTER_FILE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

# =============================================================================
# GENERAL HELPERS
# =============================================================================

def download_page_urls(url):
    """Return all ZIP URLs listed on a DWD directory page."""

    print(f"\nReading DWD directory:")
    print(url)

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    urls = []

    for link in soup.find_all("a"):
        href = link.get("href")

        if href and href.endswith(".zip"):
            urls.append(url + href)

    print(f"Found {len(urls)} station ZIP files.")

    return urls


def get_date_context():
    """
    Determine previous day and current day from the local system date.

    The script is intended to run in WSL/local time.
    """

    today = pd.Timestamp.now().normalize()
    previous_day = today - pd.Timedelta(days=1)

    print("\nDate context:")
    print(f"  Previous day : {previous_day.date()}")
    print(f"  Current day  : {today.date()}")

    return previous_day, today


# =============================================================================
# DWD 10-MINUTE AIR TEMPERATURE DATA
# =============================================================================

def load_10min_station_zip(zip_url, target_date):
    """
    Read a DWD 10-minute air-temperature ZIP,
    extract target_date, and calculate the daily mean
    temperature for each station.
    """
    max_tries = 5
    for attempt in range(max_tries):
        try:
            response = requests.get(
                zip_url,
                timeout=30,
            )
            response.raise_for_status()
            break

        except requests.RequestException as exc:
            if attempt == max_tries-1:
                raise RuntimeError(
                    f"Failed after {max_tries} attempts: {exc}"
                )

            print(
                f"\nRetrying {zip_url.split('/')[-1]} "
                f"({attempt + 1}/3): {exc}"
            )

            time.sleep(2)

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:

        data_file = next(
            name for name in z.namelist()
            if name.startswith("produkt_") and name.endswith(".txt")
        )

        with z.open(data_file) as f:
            df = pd.read_csv(
                f,
                sep=";",
                usecols=[
                    "STATIONS_ID",
                    "MESS_DATUM",
                    "TT_10",
                ],
                na_values=[-999, -999.0],
            )
        # Explicitly convert temperature to numeric
        df["TT_10"] = pd.to_numeric(
            df["TT_10"],
            errors="coerce",
        )
        # DWD missing-value markers
        df.loc[
            df["TT_10"] <= -900,
            "TT_10"
        ] = np.nan

    df["datetime"] = pd.to_datetime(
        df["MESS_DATUM"].astype(str),
        format="%Y%m%d%H%M",
        errors="coerce",
    )

    target_date = pd.Timestamp(target_date).normalize()

    df = df[
        df["datetime"].dt.normalize() == target_date
    ].copy()

    df = df.dropna(
        subset=["TT_10"]
    ).copy()

    if df.empty:
        return pd.DataFrame(
            columns=[
                "STATIONS_ID",
                "date",
                "temperature",
            ]
        )

    df = (
        df.groupby("STATIONS_ID", as_index=False)
        .agg(
            temperature=("TT_10", "mean"),
        )
    )

    df["date"] = target_date

    df["STATIONS_ID"] = (
        df["STATIONS_ID"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.zfill(5)
    )

    return df[
        [
            "STATIONS_ID",
            "date",
            "temperature",
        ]
    ]


def download_previous_day(target_date):
    """Download previous-day daily mean observations."""

    print("\n" + "=" * 70)
    print("DOWNLOADING PREVIOUS DAY")
    print("=" * 70)

    station_urls = download_page_urls(RECENT_URL)

    all_data = []

    for i, url in enumerate(station_urls, start=1):
        update_heartbeat()
        print(
            f"\rPrevious day | station {i}/{len(station_urls)}",
            end="",
            flush=True,
        )
        try:
            df = load_10min_station_zip(
                url,
                target_date,
            )

            if df is not None and not df.empty:
                all_data.append(df)

        except Exception as exc:
            print(f"\nSkipping {url}: {exc}")

    print()

    if not all_data:
        raise RuntimeError(
            f"No observations found for {target_date.date()}"
        )

    result = pd.concat(
        all_data,
        ignore_index=True,
    )

    result["STATIONS_ID"] = (
        result["STATIONS_ID"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.zfill(5)
    )

    result = (
        result
        .drop_duplicates(
            subset=["STATIONS_ID", "date"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    print(
        f"Previous day: {len(result)} station observations"
    )

    return result


def download_current_day(target_date):
    """Download current-day observations from DWD now/."""

    print("\n" + "=" * 70)
    print("DOWNLOADING CURRENT DAY")
    print("=" * 70)

    station_urls = download_page_urls(NOW_URL)

    all_data = []

    for i, url in enumerate(station_urls, start=1):
        update_heartbeat()
        print(
            f"\rCurrent day | station {i}/{len(station_urls)}",
            end="",
            flush=True,
        )

        try:
            df = load_10min_station_zip(
                url,
                target_date,
            )

            if df is not None and not df.empty:
                all_data.append(df)

        except Exception as exc:
            print(f"\nSkipping {url}: {exc}")

    print()

    if not all_data:
        raise RuntimeError(
            f"No current-day observations found for {target_date.date()}"
        )

    result = pd.concat(
        all_data,
        ignore_index=True,
    )

    result["STATIONS_ID"] = (
        result["STATIONS_ID"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.zfill(5)
    )

    result = (
        result
        .drop_duplicates(
            subset=["STATIONS_ID", "date"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    print(
        f"Current day: {len(result)} station observations"
    )

    return result


# =============================================================================
# PERSISTENT CURRENT-MONTH STATION DATA
# =============================================================================

def get_station_file(month):
    """
    Return the persistent station file for YYYY-MM.
    """

    return (
        CURRENT_STATION_DIR
        / f"{month.strftime('%Y-%m')}.txt"
    )


def initialise_current_month_data(month):
    """
    If the persistent current-month file exists, load it.
    Otherwise initialise it from the existing annual
    station-wise historical file.
    """

    station_file = get_station_file(month)

    # ---------------------------------------------------------------------
    # Load existing persistent current-month data
    # ---------------------------------------------------------------------

    if station_file.exists():
        print(
            f"\nLoading persistent station data:"
            f"\n  {station_file}"
        )

        df = pd.read_csv(
            station_file,
            sep="\t",
        )

        df["date"] = pd.to_datetime(
            df["date"],
            errors="coerce",
        ).dt.normalize()

        return df

    # ---------------------------------------------------------------------
    # Initialise from annual historical data
    # ---------------------------------------------------------------------

    print(
        "\nNo persistent current-month station file found."
    )

    historical_file = (
        BASE_DIR
        / f"DWD_dailymeans_station-wise_{YEAR}.txt"
    )

    if not historical_file.exists():
        raise FileNotFoundError(
            "Could not initialise current-month station data.\n"
            f"Missing:\n{historical_file}"
        )

    print(
        "Initialising current month from annual station data:"
    )
    print(f"  {historical_file}")

    df = pd.read_csv(
        historical_file,
        sep="\t",
    )

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce",
    ).dt.normalize()

    # Only retain the current month
    df = df[
        (df["date"].dt.year == month.year)
        & (df["date"].dt.month == month.month)
    ].copy()

    df = df.rename(
        columns={
            "TMK": "temperature",
        }
    )

    # Ensure expected columns
    required = [
        "STATIONS_ID",
        "date",
        "temperature",
        "elevation",
        "lat",
        "lon",
    ]

    df = df[required].copy()

    df["STATIONS_ID"] = (
        df["STATIONS_ID"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.zfill(5)
    )
    df["source"] = "historical"
    # Make sure there is only one observation per station/day
    df = (
        df
        .drop_duplicates(
            subset=["STATIONS_ID", "date"],
            keep="last",
        )
        .reset_index(drop=True)
    )
    station_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    df.to_csv(
        station_file,
        sep="\t",
        index=False,
        float_format="%.6f",
    )
    print(
        f"Initialised {len(df)} station observations."
    )
    return df


def update_current_month_station_data(
    existing,
    previous_day_data,
    current_day_data,
):
    """
    Replace observations for the previous and current day.

    Preserve other current-month observations. When current-month
    station metadata is missing, fall back to the previous month's
    persistent station data.
    """

    previous_date = pd.Timestamp(
        previous_day_data["date"].iloc[0]
    ).normalize()

    current_date = pd.Timestamp(
        current_day_data["date"].iloc[0]
    ).normalize()

    print("\nUpdating persistent station data:")
    print(f"  replacing {previous_date.date()}")
    print(f"  replacing {current_date.date()}")

    existing = existing.copy()

    # Normalize dates and station IDs.
    existing["date"] = pd.to_datetime(
        existing["date"],
        errors="coerce",
    ).dt.normalize()

    def normalize_station_ids(df):
        df = df.copy()
        df["STATIONS_ID"] = (
            df["STATIONS_ID"]
            .astype(str)
            .str.replace(".0", "", regex=False)
            .str.zfill(5)
        )
        return df

    existing = normalize_station_ids(existing)

    previous_day_data = normalize_station_ids(
        previous_day_data
    )
    current_day_data = normalize_station_ids(
        current_day_data
    )
    # -------------------------------------------------------------
    # Build station metadata from the current month first, then
    # fall back to the previous month's persistent station data.
    # -------------------------------------------------------------
    metadata_columns = [
        "STATIONS_ID",
        "elevation",
        "lat",
        "lon",
    ]

    metadata_frames = []

    if not existing.empty:
        metadata_frames.append(
            existing[metadata_columns].copy()
        )

    # The day before the current date determines the previous month.
    previous_month = (
        current_date - pd.Timedelta(days=1)
    ).replace(day=1)

    previous_month_file = get_station_file(previous_month)

    if previous_month_file.exists():
        print(
            "  loading fallback station metadata from "
            f"{previous_month_file.name}"
        )

        previous_month_df = pd.read_csv(
            previous_month_file,
            sep="\t",
        )

        previous_month_df = normalize_station_ids(
            previous_month_df
        )

        metadata_frames.append(
            previous_month_df[metadata_columns].copy()
        )
    else:
        print(
            "  WARNING: previous month's station file not found: "
            f"{previous_month_file}"
        )

    if metadata_frames:
        station_metadata = pd.concat(
            metadata_frames,
            ignore_index=True,
        )
        # Prefer records with the most complete metadata.
        # When completeness is equal, current-month records
        # come first because they were appended first.
        station_metadata["_metadata_order"] = range(
            len(station_metadata)
        )

        station_metadata["_metadata_quality"] = (
            station_metadata[
                ["elevation", "lat", "lon"]
            ]
            .notna()
            .sum(axis=1)
        )

        station_metadata = (
            station_metadata
            .sort_values(
                [
                    "_metadata_quality",
                    "_metadata_order",
                ],
                ascending=[False, True],
            )
            .drop_duplicates(
                subset=["STATIONS_ID"],
                keep="first",
            )
            .drop(
                columns=[
                    "_metadata_order",
                    "_metadata_quality",
                ]
            )
        )
    else:
        station_metadata = pd.DataFrame(
            columns=metadata_columns
        )
    # -------------------------------------------------------------
    # Attach metadata to newly downloaded observations.
    # Remove any metadata columns already present in the downloads
    # to avoid merge suffixes.
    # -------------------------------------------------------------
    for name, day_data in [
        ("previous", previous_day_data),
        ("current", current_day_data),
    ]:
        day_data = day_data.drop(
            columns=[
                col
                for col in ["elevation", "lat", "lon"]
                if col in day_data.columns
            ]
        )

        day_data = day_data.merge(
            station_metadata,
            on="STATIONS_ID",
            how="left",
            validate="many_to_one",
        )

        day_data["source"] = (
            "recent" if name == "previous" else "now"
        )

        if name == "previous":
            previous_day_data = day_data
        else:
            current_day_data = day_data

    # -------------------------------------------------------------
    # Remove the two dates being refreshed.
    # -------------------------------------------------------------
    existing = existing[
        ~existing["date"].isin(
            [previous_date, current_date]
        )
    ].copy()
    # -------------------------------------------------------------
    # Combine existing observations with the fresh downloads.
    # -------------------------------------------------------------
    updated = pd.concat(
        [
            existing,
            previous_day_data,
            current_day_data,
        ],
        ignore_index=True,
    )

    updated = normalize_station_ids(updated)

    updated["date"] = pd.to_datetime(
        updated["date"],
        errors="coerce",
    ).dt.normalize()

    updated = (
        updated
        .drop_duplicates(
            subset=["STATIONS_ID", "date"],
            keep="last",
        )
        .sort_values(["date", "STATIONS_ID"])
        .reset_index(drop=True)
    )
    # -------------------------------------------------------------
    # Diagnostics.
    # -------------------------------------------------------------
    print("\nNew station metadata:")
    for label, day_data in [
        ("Previous day", previous_day_data),
        ("Current day", current_day_data),
    ]:
        complete = day_data[
            ["elevation", "lat", "lon"]
        ].notna().all(axis=1).sum()

        print(
            f"  {label} with complete metadata: "
            f"{complete}/{len(day_data)}"
        )

    return updated


def save_current_month_station_data(df, month):
    """Save persistent current-month station data."""

    station_file = get_station_file(month)

    df.to_csv(
        station_file,
        sep="\t",
        index=False,
        float_format="%.6f",
    )

    print(
        "\nSaved persistent station data:"
    )
    print(f"  {station_file}")
    print(f"  {len(df)} rows")


# =============================================================================
# LAPSE RATE
# =============================================================================

def calculate_monthly_slope(df, month):
    """
    Calculate least-squares temperature/elevation slope for the
    current month.

    This is the same covariance/variance formulation used by the
    historical processing script.
    """

    group = df[
        (df["date"].dt.year == month.year)
        & (df["date"].dt.month == month.month)
    ].copy()

    group = group.dropna(
        subset=[
            "temperature",
            "elevation",
        ]
    )
    # Remove DWD missing-value markers / physically invalid temperatures
    group = group[
        group["temperature"] > -100
    ].copy()

    if len(group) < 2:
        raise RuntimeError(
            "Not enough station observations for regression."
        )

    X = group["elevation"].to_numpy(dtype=float)
    Y = group["temperature"].to_numpy(dtype=float)

    variance = np.sum(
        (X - np.mean(X)) ** 2
    )

    if variance == 0:
        raise RuntimeError(
            "Elevation variance is zero; cannot calculate lapse rate."
        )

    covariance = np.sum(
        (X - np.mean(X))
        * (Y - np.mean(Y))
    )

    slope = covariance / variance

    print("\nCurrent-month regression:")
    print(f"  Month: {month.strftime('%Y-%m')}")
    print(f"  Observations: {len(group)}")
    print(f"  Slope: {slope:.9f} °C/m")
    print(f"  Slope: {slope * 100:.6f} °C/100m")

    return slope, len(group)


def update_lapse_rate_file(
    month,
    slope,
    n_observations,
):
    """
    Replace the current month's entry in the annual lapse-rate file.
    All other months remain untouched.
    """

    if LAPSE_RATE_FILE.exists():

        lapse_df = pd.read_csv(
            LAPSE_RATE_FILE,
            sep="\t",
        )

    else:

        lapse_df = pd.DataFrame(
            columns=[
                "year",
                "month",
                "lapse_rate_per_m",
                "lapse_rate_per_100m",
            ]
        )

    # Remove existing entry for this year/month
    lapse_df = lapse_df[
        ~(
            (lapse_df["year"] == month.year)
            & (lapse_df["month"] == month.month)
        )
    ].copy()

    new_row = pd.DataFrame(
        [
            {
                "year": month.year,
                "month": month.month,
                "lapse_rate_per_m": slope,
                "lapse_rate_per_100m": slope * 100,
            }
        ]
    )

    lapse_df = pd.concat(
        [lapse_df, new_row],
        ignore_index=True,
    )

    lapse_df = lapse_df.sort_values(
        ["year", "month"]
    )

    lapse_df.to_csv(
        LAPSE_RATE_FILE,
        sep="\t",
        index=False,
        float_format="%.9f",
    )

    print("\nUpdated lapse-rate file:")
    print(f"  {LAPSE_RATE_FILE}")
    print(
        f"  {month.strftime('%Y-%m')}: "
        f"{slope:.9f} °C/m "
        f"({slope * 100:.6f} °C/100m)"
    )


# =============================================================================
# STATIC GRID
# =============================================================================

def load_static_grid():
    """
    Load the existing Germany grid instead of rebuilding it on every run.
    """

    if not STATIC_GRID_FILE.exists():
        raise FileNotFoundError(
            f"Static grid not found:\n{STATIC_GRID_FILE}"
        )

    print("\nLoading static Germany grid:")
    print(f"  {STATIC_GRID_FILE}")

    data = np.load(
        STATIC_GRID_FILE,
        allow_pickle=True,
    )

    required = [
        "grid_lon",
        "grid_lat",
        "germany_mask",
        "DEM_grid",
        "projected_coords",
    ]

    for name in required:
        if name not in data:
            raise KeyError(
                f"'{name}' not found in static grid."
            )

    grid_lon = data["grid_lon"]
    grid_lat = data["grid_lat"]
    germany_mask = data["germany_mask"]
    DEM_grid = data["DEM_grid"]
    coords = data["projected_coords"]

    print(f"  Grid shape: {grid_lon.shape}")

    return (
        grid_lon,
        grid_lat,
        germany_mask,
        DEM_grid,
        coords,
    )


# =============================================================================
# RASTER CALCULATION
# =============================================================================

def calculate_daily_raster(
    group,
    slope,
    germany_mask,
    DEM_grid,
    coords,
    transformer,
):
    """
    Calculate the daily DWD raster using the supplied monthly slope.
    """

    print("\nDEBUG: raster input")
    print("Rows before dropna:", len(group))
    print(
        group[
            [
                "STATIONS_ID",
                "date",
                "temperature",
                "elevation",
                "lat",
                "lon",
            ]
        ].head()
    )
    print("\nMissing values:")
    print(
        group[
            [
                "temperature",
                "elevation",
                "lat",
                "lon",
            ]
        ].isna().sum()
    )

    group = group.dropna(
        subset=[
            "temperature",
            "elevation",
            "lat",
            "lon",
        ]
    ).copy()

    if len(group) < 20:
        print(
            f"Only {len(group)} stations available; "
            "skipping raster."
        )
        return None

    X = group["elevation"].to_numpy(dtype=float)
    Y = group["temperature"].to_numpy(dtype=float)

    # Reduce station temperatures to sea level
    T_sea = Y - slope * X

    # Project stations to EPSG:3035
    sx, sy = transformer.transform(
        group["lon"].to_numpy(dtype=float),
        group["lat"].to_numpy(dtype=float),
    )

    station_coords = np.column_stack(
        [sx, sy]
    )

    tree = cKDTree(station_coords)

    # Nearest K stations
    dist, idx = tree.query(
        coords,
        k=K,
    )

    valid = dist < MAX_DIST

    n_contrib = np.sum(
        valid,
        axis=1,
    )

    avg_stations_per_grid = np.mean(
        n_contrib
    )

    # Mean distance
    masked_dist = np.where(
        valid,
        dist,
        0.0,
    )

    count_dist = valid.sum(axis=1)

    mean_dist_per_grid = np.divide(
        masked_dist.sum(axis=1),
        count_dist,
        out=np.full(
            count_dist.shape,
            np.nan,
        ),
        where=count_dist > 0,
    )

    overall_mean_distance = np.nanmean(
        mean_dist_per_grid
    )

    # Inverse Distance Weighting (IDW)
    weights = 1.0 / (
        dist**2 + 1e-12
    )

    weights[~valid] = 0.0

    weight_sum = np.sum(
        weights,
        axis=1,
    )

    weight_sum[
        weight_sum == 0
    ] = np.nan

    T_interp = (
        np.sum(
            weights * T_sea[idx],
            axis=1,
        )
        / weight_sum
    )
    grid_T_sea = T_interp.reshape(
        germany_mask.shape
    )
    # Add elevation back
    grid_T = (
        grid_T_sea
        + slope * DEM_grid
    )
    # Germany only
    grid_T = np.where(
        germany_mask,
        grid_T,
        np.nan,
    )
    # Raw raster mean
    mean_temp_raw = np.nanmean(
        grid_T
    )
    # Bias correction to station mean
    station_mean = np.mean(Y)

    grid_T += (
        station_mean
        - mean_temp_raw
    )
    mean_temp_corr = np.nanmean(
        grid_T
    )
    n_grid_valid = np.sum(
        ~np.isnan(grid_T)
    )

    return {
        "t_raw": mean_temp_raw,
        "n_sta": len(group),
        "avg_sta_grid": avg_stations_per_grid,
        "min_sta": np.min(n_contrib),
        "max_sta": np.max(n_contrib),
        "mean_dist": overall_mean_distance,
        "n_grid_points": n_grid_valid,
    }

# =============================================================================
# DAILY FILE UPDATE
# =============================================================================
def update_daily_raster_file(
    previous_date,
    current_date,
    previous_row,
    current_row,
):
    """
    Replace previous-day and current-day rows in the existing
    DWD daily raster file.
    """

    if not DAILY_RASTER_FILE.exists():
        raise FileNotFoundError(
            "Existing daily raster file not found:\n"
            f"{DAILY_RASTER_FILE}"
        )

    print("\nLoading existing daily raster file:")
    print(f"  {DAILY_RASTER_FILE}")

    df = pd.read_csv(
        DAILY_RASTER_FILE
    )

    df["date"] = pd.to_datetime(
        df["date"]
    )

    dates_to_replace = [
        previous_date,
        current_date,
    ]

    # Remove existing versions of both days
    df = df[
        ~df["date"].isin(
            dates_to_replace
        )
    ].copy()

    new_rows = pd.DataFrame(
        [
            previous_row,
            current_row,
        ]
    )

    new_rows["date"] = pd.to_datetime(
        new_rows["date"]
    )

    # Keep same column structure as existing file
    for column in df.columns:

        if column not in new_rows.columns:

            new_rows[column] = np.nan

    new_rows = new_rows[
        df.columns
    ]

    df = pd.concat(
        [
            df,
            new_rows,
        ],
        ignore_index=True,
    )

    df = (
        df
        .sort_values("date")
        .reset_index(drop=True)
    )

    df.to_csv(
        DAILY_RASTER_FILE,
        index=False,
        float_format="%.4f",
    )

    print("\nUpdated daily raster file:")
    print(f"  {DAILY_RASTER_FILE}")
    print(
        f"  Replaced: {previous_date.date()}"
    )
    print(
        f"  Replaced: {current_date.date()}"
    )
    print(
        f"  Total rows: {len(df)}"
    )
# =============================================================================
# MONTHLY FILE UPDATE
# =============================================================================
def update_monthly_raster_file(cutoff_date):
    """
    Recalculate monthly rastered means from the updated daily raster file.

    The current month's mean is calculated only from completed days
    through cutoff_date. For the normal 00Z run, cutoff_date is the
    previous day.

    All earlier months remain unchanged because all their daily values
    are already complete.
    """

    print("\n" + "=" * 70)
    print("UPDATING MONTHLY RASTER FILE")
    print("=" * 70)

    cutoff_date = pd.Timestamp(cutoff_date).normalize()

    print(
        f"Monthly raster cutoff: "
        f"{cutoff_date.date()}"
    )

    # ------------------------------------------------------------------
    # Load updated daily raster file
    # ------------------------------------------------------------------

    results_df = pd.read_csv(
        DAILY_RASTER_FILE
    )

    results_df["date"] = pd.to_datetime(
        results_df["date"]
    ).dt.normalize()

    # ------------------------------------------------------------------
    # Exclude the current day from the current month's mean.
    #
    # Keep:
    #   - all dates before the current month
    #   - current-month dates through cutoff_date
    #
    # This is important because the daily raster file also contains
    # the current day's raster, which must NOT enter the observed
    # monthly running mean.
    # ------------------------------------------------------------------

    current_month_start = cutoff_date.replace(day=1)

    results_df = results_df[
        (results_df["date"] < current_month_start)
        |
        (
            (results_df["date"] >= current_month_start)
            & (results_df["date"] <= cutoff_date)
        )
    ].copy()

    # Create month column
    results_df["month"] = (
        results_df["date"]
        .dt.to_period("M")
        .astype(str)
    )

    # ------------------------------------------------------------------
    # Calculate monthly raster means
    # ------------------------------------------------------------------

    monthly_df = (
        results_df
        .groupby("month")[["t_raw"]]
        .mean()
        .reset_index()
    )

    # ------------------------------------------------------------------
    # Load official DWD monthly means
    # ------------------------------------------------------------------

    official_df = pd.read_csv(
        OFFICIAL_MONTHLY_FILE
    )

    official_long = official_df.melt(
        id_vars=["Year"],
        value_vars=[
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
        var_name="month_str",
        value_name="t_official",
    )

    official_long["month_num"] = (
        pd.to_datetime(
            official_long["month_str"],
            format="%b",
        ).dt.month
    )

    official_long["month"] = (
        official_long["Year"].astype(str)
        + "-"
        + official_long["month_num"]
        .astype(str)
        .str.zfill(2)
    )

    # ------------------------------------------------------------------
    # Merge official means
    # ------------------------------------------------------------------

    monthly_df = monthly_df.merge(
        official_long[
            ["month", "t_official"]
        ],
        on="month",
        how="left",
    )

    # ------------------------------------------------------------------
    # Difference
    # ------------------------------------------------------------------
    monthly_df["diff_raw"] = (
        monthly_df["t_raw"]
        - monthly_df["t_official"]
    )
    monthly_df["month"] = (
        monthly_df["month"].astype(str)
    )
    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    monthly_df.to_csv(
        MONTHLY_RASTER_FILE,
        index=False,
        float_format="%.4f",
    )
    print("\nUpdated monthly raster file:")
    print(f"  {MONTHLY_RASTER_FILE}")
    print(
        monthly_df.tail(3).to_string(
            index=False
        )
    )
# =============================================================================
# MAIN
# =============================================================================
def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run",
        choices=["00", "12"],
        required=True,
        help="Forecast cycle: 00 or 12",
    )
    args = parser.parse_args()
    run = args.run

    reset_heartbeat()
    print(
        f"Forecast run: {run}Z"
    )
    print("Starting incremental DWD update...")
    print("\n")
    print("=" * 70)
    print("DWD CURRENT-MONTH UPDATE")
    print("=" * 70)
    previous_date, current_date = (
        get_date_context()
    )
    current_month = current_date.replace(
        day=1
    )
    # -------------------------------------------------------------------------
    # 1-3. Download data
    # -------------------------------------------------------------------------
    previous_day_data = (
        download_previous_day(
            previous_date
        )
    )
    update_heartbeat()
    current_day_data = (
        download_current_day(
            current_date
        )
    )
    update_heartbeat()
    print("\nDEBUG CURRENT-DAY DATA")

    print(
        "Stations:",
        len(current_day_data)
    )
    print(
        "Station mean temperature:",
        current_day_data["temperature"].mean()
    )
    print(
        "Minimum station temperature:",
        current_day_data["temperature"].min()
    )
    print(
        "Maximum station temperature:",
        current_day_data["temperature"].max()
    )
    print(
        "Median station temperature:",
        current_day_data["temperature"].median()
    )
    print(
        current_day_data["temperature"].describe()
    )
    # -------------------------------------------------------------------------
    # 4. Load persistent current-month data
    # -------------------------------------------------------------------------

    station_df = (
        initialise_current_month_data(
            current_month
        )
    )

    # -------------------------------------------------------------------------
    # 5. Replace previous/current day
    # -------------------------------------------------------------------------

    station_df = (
        update_current_month_station_data(
            station_df,
            previous_day_data,
            current_day_data,
        )
    )
    update_heartbeat()
    save_current_month_station_data(
        station_df,
        current_month,
    )
    
    # -------------------------------------------------------------------------
    # 6. Recalculate current-month regression
    # -------------------------------------------------------------------------

    slope, n_obs = (
        calculate_monthly_slope(
            station_df,
            current_month,
        )
    )
    update_heartbeat()
    # -------------------------------------------------------------------------
    # 7. Update monthly lapse-rate file
    # -------------------------------------------------------------------------

    update_lapse_rate_file(
        current_month,
        slope,
        n_obs,
    )

    # -------------------------------------------------------------------------
    # Load static grid
    # -------------------------------------------------------------------------

    (
        grid_lon,
        grid_lat,
        germany_mask,
        DEM_grid,
        coords,
    ) = load_static_grid()

    transformer = Transformer.from_crs(
        "EPSG:4326",
        REPROJECTION,
        always_xy=True,
    )

    # -------------------------------------------------------------------------
    # 8. Previous-day raster
    # -------------------------------------------------------------------------

    print("\n" + "=" * 70)
    print(
        f"RASTERISING PREVIOUS DAY: "
        f"{previous_date.date()}"
    )
    print("=" * 70)

    print("\nDEBUG: station date information")
    print("date dtype:", station_df["date"].dtype)
    print("date min:", station_df["date"].min())
    print("date max:", station_df["date"].max())
    print("previous_date:", previous_date)
    print("previous_date type:", type(previous_date))
    print("\nDEBUG: last 10 unique dates:")
    print(
        station_df["date"]
        .dropna()
        .sort_values()
        .unique()[-10:]
    )
    print("\nDEBUG: exact previous-date matches:")
    print(
        (
            station_df["date"].dt.normalize()
            == pd.Timestamp(previous_date).normalize()
        ).sum()
    )

    previous_group = station_df[
        station_df["date"].dt.normalize()
        == previous_date.normalize()
    ].copy()

    previous_stats = (
        calculate_daily_raster(
            previous_group,
            slope,
            germany_mask,
            DEM_grid,
            coords,
            transformer,
        )
    )
    update_heartbeat()
    if previous_stats is None:
        raise RuntimeError(
            "Could not calculate previous-day raster."
        )

    previous_row = {
        "date": previous_date,
        "t_raw": previous_stats["t_raw"],
        "n_sta": previous_stats["n_sta"],
        "avg_sta_grid": previous_stats["avg_sta_grid"],
        "min_sta": previous_stats["min_sta"],
        "max_sta": previous_stats["max_sta"],
        "mean_dist": previous_stats["mean_dist"],
        "n_grid_points": previous_stats["n_grid_points"],
        "month": previous_date.strftime("%Y-%m"),
    }

    # -------------------------------------------------------------------------
    # 9. Current-day raster
    # -------------------------------------------------------------------------

    print("\n" + "=" * 70)
    print(
        f"RASTERISING CURRENT DAY: "
        f"{current_date.date()}"
    )
    print("=" * 70)

    current_group = station_df[
        station_df["date"].dt.normalize()
        == current_date.normalize()
    ].copy()

    current_stats = (
        calculate_daily_raster(
            current_group,
            slope,
            germany_mask,
            DEM_grid,
            coords,
            transformer,
        )
    )
    update_heartbeat()
    if current_stats is None:
        raise RuntimeError(
            "Could not calculate current-day raster."
        )

    current_row = {
        "date": current_date,
        "t_raw": current_stats["t_raw"],
        "n_sta": current_stats["n_sta"],
        "avg_sta_grid": current_stats["avg_sta_grid"],
        "min_sta": current_stats["min_sta"],
        "max_sta": current_stats["max_sta"],
        "mean_dist": current_stats["mean_dist"],
        "n_grid_points": current_stats["n_grid_points"],
        "month": current_date.strftime("%Y-%m"),
    }

    # -------------------------------------------------------------------------
    # 10-12. Update daily raster file
    # -------------------------------------------------------------------------
    update_daily_raster_file(
        previous_date,
        current_date,
        previous_row,
        current_row,
    )
    update_heartbeat()

    # -------------------------------------------------------------------------
    # 13. Update monthly raster only during the 00Z run
    #
    # The daily raster is updated for BOTH previous and current day on
    # both 00Z and 12Z runs.
    #
    # The monthly observed mean, however, only advances at 00Z and uses
    # the previous day as its cutoff.
    # -------------------------------------------------------------------------
    if run == "00":

        update_monthly_raster_file(
            cutoff_date=previous_date
        )

        update_heartbeat()

    else:

        print(
            "\n12Z run:"
        )
        print(
            "  Monthly raster file is left unchanged."
        )
        print(
            f"  It continues to represent observations through "
            f"{previous_date.date()}."
        )

    print("\n")
    print("=" * 70)
    print("DWD CURRENT-MONTH UPDATE COMPLETE")
    print("=" * 70)
    print(
        f"Month: {current_month.strftime('%Y-%m')}"
    )
    print(
        f"Lapse rate: {slope:.9f} °C/m"
    )
    print(
        f"Previous day: {previous_date.date()}"
    )
    print(
        f"Current day:  {current_date.date()}"
    )
    print("=" * 70)
    update_heartbeat()
    print("\nDWD incremental update completed successfully.")

if __name__ == "__main__":
    main()