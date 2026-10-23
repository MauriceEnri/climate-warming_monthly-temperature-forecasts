import pandas as pd
import numpy as np
import xarray as xr
import requests
import bz2
import shutil
from pathlib import Path

from config import FORECAST_DIR, NORMALIZED_DIR
from processing.normalise_forecast import normalize_forecast


def download_and_unpack(url, outfile):
    compressed = outfile.with_suffix(outfile.suffix + ".bz2")

    print(f"Downloading: {url}")

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(30, 120)
        ) as r:
            r.raise_for_status()

            with open(compressed, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

    except Exception:
        if compressed.exists():
            compressed.unlink()
        raise

    if compressed.stat().st_size == 0:
        compressed.unlink()
        raise RuntimeError(f"Downloaded archive is empty: {compressed}")

    try:
        with bz2.open(compressed, "rb") as src:
            with open(outfile, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except Exception:
        if outfile.exists():
            outfile.unlink()
        raise
    finally:
        if compressed.exists():
            compressed.unlink()

    if outfile.stat().st_size == 0:
        outfile.unlink()
        raise RuntimeError(f"Unpacked GRIB file is empty: {outfile}")

    return outfile


def ensure_icon_coordinates(run, date):
    static_dir = FORECAST_DIR / "ICON_EU" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    clat_file = static_dir / "clat.grib2"
    clon_file = static_dir / "clon.grib2"

    if not clat_file.exists():
        url = (
            f"https://opendata.dwd.de/weather/nwp/"
            f"icon-eps/grib/{run}/clat/"
            f"icon-eps_global_icosahedral_time-invariant_"
            f"{date}{run}_clat.grib2.bz2"
        )
        download_and_unpack(url, clat_file)

    if not clon_file.exists():
        url = (
            f"https://opendata.dwd.de/weather/nwp/"
            f"icon-eps/grib/{run}/clon/"
            f"icon-eps_global_icosahedral_time-invariant_"
            f"{date}{run}_clon.grib2.bz2"
        )
        download_and_unpack(url, clon_file)

    return clat_file, clon_file

def download_icon_step(date, run, step):
    grib_dir = FORECAST_DIR / "ICON_EU" / "grib"
    grib_dir.mkdir(parents=True, exist_ok=True)

    outfile = grib_dir / f"ICON_EU_{date}_{run}Z_f{step:03d}.grib2"

    if outfile.exists() and outfile.stat().st_size > 0:
        return outfile

    if outfile.exists():
        outfile.unlink()

    filename = (
        f"icon-eps_global_icosahedral_single-level_"
        f"{date}{run}_{step:03d}_t_2m.grib2.bz2"
    )
    url = (
        f"https://opendata.dwd.de/weather/nwp/"
        f"icon-eps/grib/{run}/t_2m/{filename}"
    )

    print(f"Downloading forecast step {step:03d}")
    return download_and_unpack(url, outfile)

def download_icon(date, run):
    # ICON-EU EPS forecast hours
    if run == "00":
        steps = (
            list(range(0, 121, 6)) +
            list(range(132, 181, 12))
        )
    if run == "12":
        steps = (
            list(range(0, 121, 6)) +
            list(range(132, 169, 12))
        )
    #static coordinates
    clat_file, clon_file = ensure_icon_coordinates(run, date)
    print("[ICON-EU] Opening clat...")
    clat_ds = xr.open_dataset(
        clat_file,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""}
    )
    print("[ICON-EU] clat opened.")
    print("[ICON-EU] Opening clon...")
    clon_ds = xr.open_dataset(
        clon_file,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""}
    )
    print("[ICON-EU] clon opened.")

    latitude = clat_ds["tlat"].values
    longitude = clon_ds["tlon"].values
    print(f"[ICON-EU] Coordinate grid: {latitude.shape}")
    print(f"[ICON-EU] Latitude points: {latitude.size}")
    print(f"[ICON-EU] Longitude points: {longitude.size}")

    #containers for all members
    member_temperatures = {}
    valid_times = []
    init_time = None

    for step in steps:
        temp_file = download_icon_step(date, run, step)

        ds = xr.open_dataset(temp_file, engine="cfgrib")

        if init_time is None:
            init_time = pd.Timestamp(ds["time"].values)

        valid_times.append(pd.Timestamp(ds["valid_time"].values))

        numbers = ds["number"].values

        for number in numbers:
            member_ds = ds.sel(number=number)
            member_name = (
                "ICON_EU"
                if number == 0
                else f"P{int(number):02d}"
            )
            temperature = member_ds["t2m"].values - 273.15

            member_temperatures.setdefault(member_name, []).append(temperature)

        ds.close()
    #delete temporary GRIB immediately when not needed anymore
    for step in steps:
        temp_file = (
            FORECAST_DIR
            / "ICON_EU" 
            / "grib"
            / f"ICON_EU_{date}_{run}Z_f{step:03d}.grib2"
        )
        if temp_file.exists():
            temp_file.unlink()

    #save one NetCDF per member
    for member_name, temperature_list in member_temperatures.items():
        temperature = np.stack(temperature_list, axis=0)
        normalized = normalize_forecast(
            temperature=temperature,
            latitude=latitude,
            longitude=longitude,
            valid_times=valid_times,
            init_time=init_time,
            model_name="ICON_EU",
        )
        member_dir = NORMALIZED_DIR / "ICON_EU" / member_name
        member_dir.mkdir(parents=True, exist_ok=True)

        normalised_file = (
            member_dir /
            f"{member_name}_{date}_{run}Z.nc"
        )
        normalized.to_netcdf(normalised_file)

        print(f"[OK] Saved {normalised_file}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("--date", required=True, help="YYYYMMDD")
    parser.add_argument("--run", default="00", help="00, 06, 12 or 18")

    args = parser.parse_args()

    download_icon(
        date=args.date,
        run=args.run
    )