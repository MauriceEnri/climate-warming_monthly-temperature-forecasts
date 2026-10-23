from pathlib import Path
import glob
import matplotlib.pyplot as plt
import pandas as pd
import matplotlib.dates as mdates
import numpy as np
import argparse
from datetime import timedelta
from matplotlib.ticker import MultipleLocator
import sys
import subprocess
from config import (
    PROJECT_DIR,
    MODELS,
    ENSEMBLE_MEMBERS,
    NORMALIZED_DIR,
    RESULT_DIR,
    DATA_DIR,
    MONTHLY_MEAN_FILE,
    CURRENT_DAILY_MEAN_FILE
)
from processing.process_model import process_model

def build_reference_running_mean(month, forecast_year):
    """
    Returns the 1991-2020 climatological running mean for one month.
    """
    files = sorted(
        glob.glob(
            str(
                DATA_DIR 
                / "current_monthly_means" 
                / "1991-2020"
                / "DWD_daily_raster_sta25_dist120000.000_EPSG:3035_*.txt"
            )
        )
    )
    all_days = []

    for f in files:
        df = pd.read_csv(f)

        df["date"] = pd.to_datetime(df["date"])

        df = df[
            df["date"].dt.month == month
        ]
        if len(df) == 0:
            continue
        df["day"] = df["date"].dt.day

        all_days.append(
            df[["day", "t_raw"]]
        )
    #get reference mean for each calendar day across all years
    climatology = (
        pd.concat(all_days)
        .groupby("day")["t_raw"]
        .mean()
        .reset_index()
    )
    #sort days correctly
    climatology = climatology.sort_values("day").reset_index(drop=True)
    #build running mean
    climatology["running_mean"] = (
        climatology["t_raw"]
        .expanding()
        .mean()
    )
    climatology["valid_time"] = pd.to_datetime(
        {
            "year": forecast_year,
            "month": month,
            "day": climatology["day"]
        }
    )
    return climatology

def build_reference_summer_running_mean(forecast_year):
    """
    Returns the 1991–2020 climatological running mean
    for the summer period (1 June onward).
    The running mean is calculated from the climatological
    mean temperature for each calendar day, starting on
    1 June.
    """

    files = sorted(
        glob.glob(
            str(
                DATA_DIR
                / "current_monthly_means"
                / "1991-2020"
                / "DWD_daily_raster_sta25_dist120000.000_EPSG:3035_*.txt"
            )
        )
    )
    all_days = []

    for f in files:

        df = pd.read_csv(f)

        df["date"] = pd.to_datetime(df["date"])

        # Keep June, July and August
        df = df[
            df["date"].dt.month.isin([6, 7, 8])
        ]
        if len(df) == 0:
            continue

        # Calendar day within the summer
        df["month_day"] = df["date"].dt.strftime("%m-%d")

        all_days.append(
            df[["month_day", "t_raw"]]
        )
    # ---------------------------------------------------------
    # Climatological mean for each calendar day
    # ---------------------------------------------------------
    climatology = (
        pd.concat(all_days)
        .groupby("month_day")["t_raw"]
        .mean()
        .reset_index()
    )
    # Convert month-day back to dates
    climatology["valid_time"] = pd.to_datetime(
        str(forecast_year) + "-"
        + climatology["month_day"]
    )
    climatology = (
        climatology
        .sort_values("valid_time")
        .reset_index(drop=True)
    )
    # ---------------------------------------------------------
    # Running mean from 1 June
    # ---------------------------------------------------------
    climatology["running_mean"] = (
        climatology["t_raw"]
        .expanding()
        .mean()
    )

    return climatology

def build_specific_summer_running_mean(year):
    """
    Returns the actual daily running mean for a specific summer year
    (1 June -> 31 August).

    Uses the actual daily rastered temperatures from the requested year,
    rather than the 1991–2020 climatological mean.
    """

    files = sorted(
        glob.glob(
            str(
                DATA_DIR
                / "current_monthly_means"
                / "1991-2020"
                / "DWD_daily_raster_sta25_dist120000.000_EPSG:3035_*.txt"
            )
        )
    )
    all_days = []

    for f in files:
        df = pd.read_csv(f)
        df["date"] = pd.to_datetime(df["date"])
        # Keep only the requested year
        df = df[
            df["date"].dt.year == year
        ]
        # Keep meteorological summer: June, July, August
        df = df[
            df["date"].dt.month.isin([6, 7, 8])
        ]
        if df.empty:
            continue

        all_days.append(
            df[["date", "t_raw"]]
        )
    # ---------------------------------------------------------
    # Check that data were found
    # ---------------------------------------------------------
    if not all_days:
        raise ValueError(
            f"No summer data found for {year}"
        )
    # ---------------------------------------------------------
    # Combine all files
    # ---------------------------------------------------------
    summer = (
        pd.concat(all_days)
        .sort_values("date")
        .drop_duplicates("date")
        .reset_index(drop=True)
    )
    summer["t_raw"] = pd.to_numeric(
        summer["t_raw"],
        errors="coerce"
    )
    # ---------------------------------------------------------
    # Running mean from 1st in first month of season in question
    # ---------------------------------------------------------
    summer["running_mean"] = (
        summer["t_raw"]
        .expanding()
        .mean()
    )
    return summer.rename(
        columns={
            "date": "valid_time"
        }
    )

def compute_monthly_running_mean(
    df,
    monthly_lookup,
    completed_days
):
    df = df.copy()

    running_mean = []

    first_forecast_month = (
        df["valid_time"].iloc[0].strftime("%Y-%m")
    )
    forecast_sum = 0.0
    forecast_days = 0
    current_month = None

    for _, row in df.iterrows():

        month = row["valid_time"].strftime("%Y-%m")

        # New month → restart accumulation
        if month != current_month:
            current_month = month
            forecast_sum = 0.0
            forecast_days = 0

            if month == first_forecast_month:
                if month in monthly_lookup.index:
                    observed_days = completed_days
                    observed_sum = (
                        monthly_lookup.loc[month]
                        * observed_days
                    )
                else:
                    observed_days = 0
                    observed_sum = 0.0
            else:
                observed_days = 0
                observed_sum = 0.0

        forecast_sum += row["t_raster"]
        forecast_days += 1

        total_sum = observed_sum + forecast_sum
        total_days = observed_days + forecast_days

        running_mean.append(
            total_sum / total_days
        )
    df["monthly_running_mean"] = running_mean

    return df

def compute_summer_running_mean(
    df,
    summer_observed_point,
    summer_observed_days
):
    """
    Calculate running mean for the meteorological summer
    starting on 1 June and ending on 31 August.

    The observed period (1 June -> day before forecast)
    is used as the starting accumulated mean, and forecast
    values are then progressively added.
    """

    df = df.copy()
    # ---------------------------------------------------------
    # Only retain 3 months in meteorological season
    # ---------------------------------------------------------
    df = df[
        df["valid_time"].dt.month.isin([6, 7, 8])
    ].copy()

    # Make sure forecast is chronological
    df = df.sort_values("valid_time").reset_index(drop=True)

    running_mean = []

    forecast_sum = 0.0
    forecast_days = 0

    observed_sum = (
        summer_observed_point * summer_observed_days
    )
    for _, row in df.iterrows():

        # Skip invalid temperatures
        if pd.isna(row["t_raster"]):
            running_mean.append(np.nan)
            continue

        forecast_sum += row["t_raster"]
        forecast_days += 1

        total_sum = (
            observed_sum +
            forecast_sum
        )
        total_days = (
            summer_observed_days +
            forecast_days
        )
        running_mean.append(
            total_sum / total_days
        )

    df["summer_running_mean"] = running_mean

    return df

parser = argparse.ArgumentParser()
parser.add_argument(
    "--date",
    type=str,
    required=True
)
parser.add_argument(
    "--run",
    type=str,
    default="00"
)
args = parser.parse_args()
run_string = (
    f"{args.date.replace('-', '')}_{args.run}Z"
)
run_dir = (
    RESULT_DIR /
    run_string
)
run_dir.mkdir(
    parents=True,
    exist_ok=True
)
# ---------------------------------------------------------------
# Find available normalised forecasts
# ---------------------------------------------------------------
model_results_raw = {}

for model_name, model_info in MODELS.items():

    ensemble_name = model_info["ensemble"]
    if ensemble_name is None:
        members = [
            model_info["oper"]
        ]
    else:
        members = ENSEMBLE_MEMBERS[ensemble_name]
    print("\n====================")
    print("PROCESSING", model_name)
    print("====================")
    ensemble_results = []

    for member in members:

        forecast_file = (
            NORMALIZED_DIR
            /
            model_name
            /
            member
            /
            f"{member}_{run_string}.nc"
        )
        if not forecast_file.exists():
            print(
                f"Skipping {member}: {forecast_file}"
            )
            continue
        print(
            "Processing:",
            model_name,
            member
        )
        df, init_time = process_model(
            model_name,
            forecast_file,
            member
        )
        #df["member"] = member
        #df["model"] = model_name
        # ---------------------------------------------------------------
        # Save individual member forecast
        # ---------------------------------------------------------------
        outfile = (
            run_dir /
            f"{model_name}_{member}_daily_forecast.txt"
        )
        df.to_csv(
            outfile,
            sep="\t",
            index=False,
            float_format="%.3f"
        )
        print(
            f"[OK] Saved {outfile}"
        )
        ensemble_results.append(df)

    if ensemble_results:
        model_results_raw[model_name] = pd.concat(
            ensemble_results,
            ignore_index=True
        )
    else:
        print(
            f"No files available for {model_name}"
        )
# ---------------------------------------------------------------
# Stop if nothing processed
# ---------------------------------------------------------------
if len(model_results_raw) == 0:
    raise RuntimeError(
        "No forecast files were processed."
    )
# ---------------------------------------------------------------
# Add monthly running means
# ---------------------------------------------------------------
current_monthly_means = pd.read_csv(
    MONTHLY_MEAN_FILE
)
monthly_lookup = (
    current_monthly_means
    .set_index("month")
    ["t_raw"]
)
first_forecast_date = init_time.normalize()

completed_days = (
    first_forecast_date.day - 1
)
# ---------------------------------------------------------------
# Summer 1991–2020 reference running mean
# ---------------------------------------------------------------
reference_summer = build_reference_summer_running_mean(
    init_time.year
)
#also get certain season's reference running mean
reference_summer_specific_year_1 = build_specific_summer_running_mean(
    2003
)
reference_summer_specific_year_2 = build_specific_summer_running_mean(
    2018
)
# ---------------------------------------------------------------
# Add last observed monthly mean point before forecast
# ---------------------------------------------------------------
if completed_days > 0:
    previous_day = (
        first_forecast_date
        - timedelta(days=1)
    )
    previous_month = previous_day.strftime("%Y-%m")
    if previous_month in monthly_lookup.index:
        observed_monthly_mean = monthly_lookup.loc[previous_month]
    else:
        observed_monthly_mean = np.nan
    observed_point_time = pd.Timestamp(previous_day)
    print(
        f"Observed monthly mean until {previous_day.date()}: "
        f"{observed_monthly_mean:.2f}°C"
    )
else:
    observed_day = None
    observed_monthly_mean = None
    observed_point_time = None
# ---------------------------------------------------------------
# Summer observed running mean: 1 June -> last observed day
# ---------------------------------------------------------------
observed_df = pd.read_csv(
    CURRENT_DAILY_MEAN_FILE,
    parse_dates=["date"]
)
summer_start = pd.Timestamp(
    first_forecast_date.year, 6, 1
)
previous_day = first_forecast_date - timedelta(days=1)

summer_observed = observed_df.loc[
    (observed_df["date"] >= summer_start) &
    (observed_df["date"] <= previous_day)
].copy()
summer_observed = (
    summer_observed
    .sort_values("date")
    .reset_index(drop=True)
)
summer_observed["t_raw"] = pd.to_numeric(
    summer_observed["t_raw"],
    errors="coerce"
)
summer_observed["running_mean"] = (
    summer_observed["t_raw"].expanding().mean()
)
summer_observed = summer_observed.rename(
    columns={"date": "valid_time"}
)
if not summer_observed.empty:
    summer_observed_point = (
        summer_observed.iloc[-1]["running_mean"]
    )
    summer_observed_point_time = (
        summer_observed.iloc[-1]["valid_time"]
    )
else:
    summer_observed_point = np.nan
    summer_observed_point_time = pd.NaT
print(
    f"Summer observed running mean until "
    f"{previous_day.date()}: "
    f"{summer_observed_point:.2f}°C"
)
#compute anomaly for summer mean
summer_reference_value = (
    reference_summer.loc[
        reference_summer["valid_time"] == summer_observed_point_time,
        "running_mean"
    ]
)
if not summer_reference_value.empty:
    summer_reference_value = summer_reference_value.iloc[0]
else:
    summer_reference_value = np.nan

summer_observed_anomaly = (
    summer_observed_point - summer_reference_value
)
# ---------------------------------------------------------------
# Calculate monthly running means and statistics per model
# ---------------------------------------------------------------
model_results = {}
model_stats = {}

for model_name, ensemble in model_results_raw.items():
    print(
        "\nCalculating ensemble statistics:",
        model_name
    )
    #calculate monthly running means member-by-member
    monthly_members = [
        compute_monthly_running_mean(
            df,
            monthly_lookup,
            completed_days
        )
        for _, df in ensemble.groupby("member")
    ]
    ensemble_monthly = pd.concat(
        monthly_members,
        ignore_index=True
    )
    print(
        "Members loaded:",
        model_name,
        ensemble_monthly["member"].unique()
    )
    stats = (
        ensemble_monthly
        .groupby("valid_time")
        ["monthly_running_mean"]
        .agg(
            ensemble_mean="mean",
            p5=lambda x: np.percentile(x,5),
            p20=lambda x: np.percentile(x,20),
            p80=lambda x: np.percentile(x,80),
            p95=lambda x: np.percentile(x,95),
            minimum="min",
            maximum="max"
        )
        .reset_index()
    )
    model_results[model_name] = ensemble_monthly
    model_stats[model_name] = stats

    stats.to_csv(
        run_dir / f"{model_name}_ensemble_{run_string}.txt",
        sep="\t",
        index=False,
        float_format="%.3f"
    )
# ---------------------------------------------------------------
# Calculate summer running means and statistics per model
# ---------------------------------------------------------------
summer_model_results = {}
summer_model_stats = {}

summer_observed_days = (
    summer_observed["valid_time"].dt.normalize().nunique()
)
for model_name, ensemble in model_results_raw.items():
    print(
        "\nCalculating summer ensemble statistics:",
        model_name
    )
    summer_members = [
        compute_summer_running_mean(
            df,
            summer_observed_point,
            summer_observed_days
        )
        for _, df in ensemble.groupby("member")
    ]
    ensemble_summer = pd.concat(
        summer_members,
        ignore_index=True
    )
    stats_summer = (
        ensemble_summer
        .groupby("valid_time")
        ["summer_running_mean"]
        .agg(
            ensemble_mean="mean",
            p5=lambda x: np.percentile(x, 5),
            p20=lambda x: np.percentile(x, 20),
            p80=lambda x: np.percentile(x, 80),
            p95=lambda x: np.percentile(x, 95),
            minimum="min",
            maximum="max"
        )
        .reset_index()
    )
    summer_model_results[model_name] = ensemble_summer
    summer_model_stats[model_name] = stats_summer
# ---------------------------------------------------------------
#function to create plots
# ---------------------------------------------------------------
def make_model_plot(
    model_stats,
    model_results,
    reference_running,
    observed_running,
    title,
    filename,
    add_observed=False,
    ytick_interval=1.0,
    running_mean_column="monthly_running_mean",
    reference_running_specific_year_1=None,
    reference_running_specific_year_2=None
):
    #distinguish between season running mean and running reference mean 
    #and monthly running mean and running reference mean
    if running_mean_column == "summer_running_mean":
        plot_observed_point_time = summer_observed_point_time
        plot_observed_value = summer_observed_point
        plot_observed_anomaly = summer_observed_anomaly
    else:
        plot_observed_point_time = observed_point_time
        plot_observed_value = observed_monthly_mean
    plot_observed_anomaly = np.nan

    models = list(model_stats.keys())

    fig, axes = plt.subplots(
        2,
        2,
        figsize=(28, 16),  #len(models)
        sharex=True
    )
    #flatten axes
    axes = axes.ravel()
    #handle single model case
    if len(models) == 1:
        axes = [axes[0]]

    for ax, model_name in zip(axes, models):

        stats = model_stats[model_name]
        ensemble = model_results[model_name]
        #get number of members in Ensemble
        n_members = (
            ensemble["member"]
            .nunique()
        )
        # -------------------------------------------------------------
        # Identify extreme members at the latest valid forecast time
        # -------------------------------------------------------------
        valid_final = ensemble.dropna(
            subset=[running_mean_column]
        )
        if valid_final.empty:
            print(
                f"WARNING: {model_name} has no valid "
                f"{running_mean_column} values."
            )
            continue

        final_time = valid_final["valid_time"].max()
        final_members = valid_final[
            valid_final["valid_time"] == final_time
        ].copy()

        if final_members.empty:
            print(
                f"WARNING: {model_name} has no members "
                f"at final time {final_time}."
            )
            continue

        coldest_member = (
            final_members
            .loc[
                final_members[running_mean_column].idxmin(),
                "member"
            ]
        )
        warmest_member = (
            final_members
            .loc[
                final_members[running_mean_column].idxmax(),
                "member"
            ]
        )
        coldest_final = (
            final_members
            .loc[
                final_members["member"] == coldest_member,
                running_mean_column
            ]
            .iloc[0]
        )
        warmest_final = (
            final_members
            .loc[
                final_members["member"] == warmest_member,
                running_mean_column
            ]
            .iloc[0]
        )
        ens_final = stats["ensemble_mean"].iloc[-1]
        # -----------------------------
        # Add observed starting point
        # -----------------------------
        ens_avg = stats[
            ["valid_time", "ensemble_mean"]
        ].copy()
        ens_min = stats[
            ["valid_time", "minimum"]
        ].copy()
        ens_max = stats[
            ["valid_time", "maximum"]
        ].copy()
        ens_p5 = stats[
            ["valid_time", "p5"]
        ].copy()
        ens_p20 = stats[
            ["valid_time", "p20"]
        ].copy()
        ens_p80 = stats[
            ["valid_time", "p80"]
        ].copy()
        ens_p95 = stats[
            ["valid_time", "p95"]
        ].copy()
        # deterministic members
        deterministic = ensemble[
            ~ensemble["member"].str.match(r"P\d+")
        ]
        # -----------------------------
        # Reference climate running mean
        # -----------------------------
        first_forecast = stats["valid_time"].min()

        panel_start = first_forecast.normalize().replace(day=1)
        panel_end = stats["valid_time"].max()

        reference_plot = reference_running.loc[
            (reference_running["valid_time"] >= panel_start)
            &
            (reference_running["valid_time"] <= panel_end)
        ].copy()
        # -------------------------------------------------------------
        # Reference value on day of available observed mean and observed anomaly
        # -------------------------------------------------------------
        reference_observed_value = (
            reference_plot.loc[
                reference_plot["valid_time"] == plot_observed_point_time,
                "running_mean"
            ]
        )
        if len(reference_observed_value):
            reference_observed_value = reference_observed_value.iloc[0]

            plot_observed_anomaly = (
                plot_observed_value
                - reference_observed_value
            )
        else:
            reference_observed_value = np.nan
            plot_observed_anomaly = np.nan

        if (
            add_observed
            and observed_running is not None
            and not observed_running.empty
        ):
            # Only use observations up to the last completed day
            observed_plot = observed_running.loc[
                (observed_running["valid_time"] >= panel_start)
                &
                (observed_running["valid_time"] <= plot_observed_point_time)
            ].copy()
            if not observed_plot.empty:
                # Last completed observed running mean
                #observed_value_plot = (
                #    observed_plot["running_mean"].iloc[-1]
                #)
                observed_value_plot = plot_observed_value
                # Add observed starting point to forecast statistics
                history_avg = pd.DataFrame({
                    "valid_time": [plot_observed_point_time],
                    "ensemble_mean": [observed_value_plot]
                })
                history_min = pd.DataFrame({
                    "valid_time": [plot_observed_point_time],
                    "minimum": [observed_value_plot]
                })
                history_max = pd.DataFrame({
                    "valid_time": [plot_observed_point_time],
                    "maximum": [observed_value_plot]
                })
                history_p5 = pd.DataFrame({
                    "valid_time": [plot_observed_point_time],
                    "p5": [observed_value_plot]
                })
                history_p20 = pd.DataFrame({
                    "valid_time": [plot_observed_point_time],
                    "p20": [observed_value_plot]
                })
                history_p80 = pd.DataFrame({
                    "valid_time": [plot_observed_point_time],
                    "p80": [observed_value_plot]
                })
                history_p95 = pd.DataFrame({
                    "valid_time": [plot_observed_point_time],
                    "p95": [observed_value_plot]
                })
                ens_avg = pd.concat(
                    [history_avg, ens_avg],
                    ignore_index=True
                )
                ens_min = pd.concat(
                    [history_min, ens_min],
                    ignore_index=True
                )
                ens_max = pd.concat(
                    [history_max, ens_max],
                    ignore_index=True
                )
                ens_p5 = pd.concat(
                    [history_p5, ens_p5],
                    ignore_index=True
                )
                ens_p20 = pd.concat(
                    [history_p20, ens_p20],
                    ignore_index=True
                )
                ens_p80 = pd.concat(
                    [history_p80, ens_p80],
                    ignore_index=True
                )
                ens_p95 = pd.concat(
                    [history_p95, ens_p95],
                    ignore_index=True
                )
                # Plot observed running mean
                ax.plot(
                    observed_plot["valid_time"],
                    observed_plot["running_mean"],
                    color="darkorange",
                    linewidth=2.5,
                    linestyle="-",
                    zorder=5,
                    label="Observed running monthly mean"
                )
                # Plot last completed observed day
                ax.scatter(
                    plot_observed_point_time,
                    plot_observed_value,  #observed_value_plot
                    color="darkorange",
                    s=40,
                    zorder=6,
                    label=(
                        f"Observed until "
                        f"{previous_day.strftime('%d %b')} | "
                        f"{plot_observed_value:.2f}°C "
                        f"({plot_observed_anomaly:+.2f}°C)"
                    )
                )
        #plot the reference running mean
        reference_final = (
            reference_plot["running_mean"].iloc[-1]
        )
        ax.plot(
            reference_plot["valid_time"],
            reference_plot["running_mean"],
            color="mediumorchid",
            linewidth=2.5,
            linestyle="-.",
            label=f"climatological reference mean 1991–2020 | {reference_final:.2f}°C"
        )
        #add reference running mean for certain years
        if reference_running_specific_year_1 is not None:

            reference_specific_year_plot_1 = (
                reference_running_specific_year_1[
                    (
                        reference_running_specific_year_1["valid_time"].dt.month
                        > panel_start.month
                    )
                    |
                    (
                        (
                            reference_running_specific_year_1["valid_time"].dt.month
                            == panel_start.month
                        )
                        &
                        (
                            reference_running_specific_year_1["valid_time"].dt.day
                            >= panel_start.day
                        )
                    )
                ]
                .copy()
            )
            # Limit to the same calendar day as panel_end
            reference_specific_year_plot_1 = (
                reference_specific_year_plot_1[
                    (
                        reference_specific_year_plot_1["valid_time"].dt.month
                        < panel_end.month
                    )
                    |
                    (
                        (
                            reference_specific_year_plot_1["valid_time"].dt.month
                            == panel_end.month
                        )
                        &
                        (
                            reference_specific_year_plot_1["valid_time"].dt.day
                            <= panel_end.day
                        )
                    )
                ]
                .copy()
            )
            if not reference_specific_year_plot_1.empty:
                # Put specific year's running mean values onto the forecast year's x-axis
                reference_specific_year_plot_1["plot_time"] = (
                    reference_specific_year_plot_1["valid_time"]
                    .apply(
                        lambda x: x.replace(year=panel_start.year)
                    )
                )
                reference_specific_year_final_1 = (
                    reference_specific_year_plot_1["running_mean"].iloc[-1]
                )
                ax.plot(
                    reference_specific_year_plot_1["plot_time"],
                    reference_specific_year_plot_1["running_mean"],
                    color="red",
                    linewidth=2.5,
                    linestyle="--",
                    label=(
                        f"2003 | "
                        f"{reference_specific_year_final_1:.2f}°C"
                    )
                )
        if reference_running_specific_year_2 is not None:

            reference_specific_year_plot_2 = (
                reference_running_specific_year_2[
                    (
                        reference_running_specific_year_2["valid_time"].dt.month
                        > panel_start.month
                    )
                    |
                    (
                        (
                            reference_running_specific_year_2["valid_time"].dt.month
                            == panel_start.month
                        )
                        &
                        (
                            reference_running_specific_year_2["valid_time"].dt.day
                            >= panel_start.day
                        )
                    )
                ]
                .copy()
            )
            # Limit to the same calendar day as panel_end
            reference_specific_year_plot_2 = (
                reference_specific_year_plot_2[
                    (
                        reference_specific_year_plot_2["valid_time"].dt.month
                        < panel_end.month
                    )
                    |
                    (
                        (
                            reference_specific_year_plot_2["valid_time"].dt.month
                            == panel_end.month
                        )
                        &
                        (
                            reference_specific_year_plot_2["valid_time"].dt.day
                            <= panel_end.day
                        )
                    )
                ]
                .copy()
            )
            if not reference_specific_year_plot_2.empty:
                # Put specific year's running mean values onto the forecast year's x-axis
                reference_specific_year_plot_2["plot_time"] = (
                    reference_specific_year_plot_2["valid_time"]
                    .apply(
                        lambda x: x.replace(year=panel_start.year)
                    )
                )
                reference_specific_year_final_2 = (
                    reference_specific_year_plot_2["running_mean"].iloc[-1]
                )
                ax.plot(
                    reference_specific_year_plot_2["plot_time"],
                    reference_specific_year_plot_2["running_mean"],
                    color="tomato",
                    linewidth=2.5,
                    linestyle="--",
                    label=(
                        f"2018 | "
                        f"{reference_specific_year_final_2:.2f}°C"
                    )
                )
        # Final values of the percentile envelopes
        p5_final = stats["p5"].iloc[-1]
        p95_final = stats["p95"].iloc[-1]
        p20_final = stats["p20"].iloc[-1]
        p80_final = stats["p80"].iloc[-1]
        # -----------------------------
        # Ensemble statistics
        # -----------------------------
        p5_anom = p5_final - reference_final
        p95_anom = p95_final - reference_final
        p20_anom = p20_final - reference_final
        p80_anom = p80_final - reference_final
        ax.fill_between(
            ens_p5["valid_time"],
            ens_p5["p5"],
            ens_p95["p95"],
            color="grey",
            alpha=0.25,
            label=f"5-95% | min {p5_final:.2f}°C ({p5_anom:+.2f}°C) | max {p95_final:.2f}°C ({p95_anom:+.2f}°C)"
        )
        ax.fill_between(
            ens_p20["valid_time"],
            ens_p20["p20"],
            ens_p80["p80"],
            color="grey",
            alpha=0.45,
            label=f"20-80% | min {p20_final:.2f}°C ({p20_anom:+.2f}°C) | max {p80_final:.2f}°C ({p80_anom:+.2f}°C)"
        )
        cold_anom = coldest_final - reference_final
        ax.plot(
            ens_min["valid_time"],
            ens_min["minimum"],
            "--",
            color="midnightblue",
            label=(
                f"Min | {coldest_member} | {coldest_final:.2f}°C ({cold_anom:+.2f}°C)"
            )
        )
        warm_anom = warmest_final - reference_final
        ax.plot(
            ens_max["valid_time"],
            ens_max["maximum"],
            "--",
            color="darkred",
            label=(
                f"Max | {warmest_member} | {warmest_final:.2f}°C ({warm_anom:+.2f}°C)"
            )
        )
        anom = ens_final - reference_final
        ax.plot(
            ens_avg["valid_time"],
            ens_avg["ensemble_mean"],
            color="black",
            linewidth=2,
            label=f"AVG | {ens_final:.2f}°C ({anom:+.2f}°C)"
        )
        # -----------------------------
        # Deterministic members
        # -----------------------------
        if add_observed:
            print("\nDEBUG OBSERVED ANCHOR")
            print("plot_observed_point_time:", plot_observed_point_time)
            print("observed_plot", observed_plot["running_mean"])
            print("plot_observed_value:    ", plot_observed_value)
            print("observed_value_plot:    ", observed_value_plot)
            print(
                "difference:             ",
                plot_observed_value - observed_value_plot
            )
            history_member = pd.DataFrame({
                "valid_time": [
                    plot_observed_point_time
                ],
                running_mean_column: [
                    plot_observed_value
                ],
                "member": [
                    "Observed"
                ]
            })
        for member in deterministic["member"].unique():
            member_df = deterministic[
                deterministic["member"] == member
            ].copy()
            if add_observed and member in [
                "GFS",
                "HRES",
                "AIFS",
                "C00"
            ]:
                member_df = pd.concat(
                    [
                        history_member,
                        member_df
                    ],
                    ignore_index=True
                )
            final_value = (
                member_df
                .loc[
                    member_df["valid_time"].idxmax(),
                    running_mean_column
                ]
            )
            if member in [
                "GFS",
                "HRES",
                "AIFS"
            ]:
                colour = "springgreen"
                linewidth = 2
            elif member == "C00":
                colour = "forestgreen"
                linewidth = 2
            else:
                colour = None
                linewidth = 1
            anom = final_value - reference_final
            if member == "GFS" or member == "HRES":
                ax.plot(
                    member_df["valid_time"],
                    member_df[running_mean_column],
                    color=colour,
                    linewidth=linewidth,
                    label=f"Oper | {final_value:.2f}°C ({anom:+.2f}°C)"
                )
            elif member == "AIFS":
                ax.plot(
                    member_df["valid_time"],
                    member_df[running_mean_column],
                    color=colour,
                    linewidth=linewidth,
                    label=f"{member}-Single | {final_value:.2f}°C ({anom:+.2f}°C)"
                )
            else:
                ax.plot(
                    member_df["valid_time"],
                    member_df[running_mean_column],
                    color=colour,
                    linewidth=linewidth,
                    label=f"{member} | {final_value:.2f}°C ({anom:+.2f}°C)"
                )
        # -----------------------------
        # Cosmetics
        # -----------------------------
        ax.tick_params(
            axis="both",
            which="major",
            labelsize=16
        )
        ax.title.set_fontsize(22)
        ax.xaxis.label.set_fontsize(16)
        ax.yaxis.label.set_fontsize(18)
        # Keep x-axis labels horizontal
        ax.tick_params(
            axis="x",
            rotation=0
        )
        if model_name == 'ICON_EU':
            ax.set_title(f"Deutscher Wetterdienst [ICON EPS] | {n_members} members", fontsize=15)
        if model_name == 'IFS' or model_name == 'AIFS':
            ax.set_title(f"European Centre for Medium-Range Weather Forecasts [{model_name}] | {n_members} members", fontsize=15)
        if model_name == 'GFS':
            ax.set_title(f"Global Forecast System [{model_name}] | {n_members} members", fontsize=15)
        ax.legend(loc="best", fontsize=11, ncols=2, facecolor="whitesmoke")
        ax.set_ylabel("[°C]")
        ax.grid(True)
        ax.yaxis.set_major_locator(
            MultipleLocator(ytick_interval)
        )
    axes[-1].xaxis.set_major_locator(
        mdates.DayLocator(interval=1)
    )
    axes[-1].xaxis.set_major_formatter(
        mdates.DateFormatter("%d.")
    )
    for ax in axes[2:]:
        ax.set_xlabel(
            "Date",
            fontsize=16,
            labelpad=10
        )
    #fig.autofmt_xdate()
    fig.suptitle(
        title,
        fontsize=18
    )
    fig.text(
        0.51, 0.006,
        "Created by Maurice Weber\n based on data from Deutscher Wetterdienst (DWD) and above forecast models",
        ha="center",
        va="bottom",
        fontsize=13
    )
    plt.tight_layout()
    plt.savefig(
        run_dir / filename,
        dpi=200,
        bbox_inches="tight"
    )
    plt.close()
# ---------------------------------------------------------------
# Split current and next month for each model
# ---------------------------------------------------------------
current_model_stats = {}
next_model_stats = {}
current_model_results = {}
next_model_results = {}

for model_name in model_stats:

    first_month = (
        model_stats[model_name]
        ["valid_time"]
        .iloc[0]
        .month
    )
    current_model_stats[model_name] = (
        model_stats[model_name]
        [
            model_stats[model_name]
            ["valid_time"]
            .dt.month
            ==
            first_month
        ]
    )
    next_model_stats[model_name] = (
        model_stats[model_name]
        [
            model_stats[model_name]
            ["valid_time"]
            .dt.month
            !=
            first_month
        ]
    )
    current_model_results[model_name] = (
        model_results[model_name]
        [
            model_results[model_name]
            ["valid_time"]
            .dt.month
            ==
            first_month
        ]
    )
    next_model_results[model_name] = (
        model_results[model_name]
        [
            model_results[model_name]
            ["valid_time"]
            .dt.month
            !=
            first_month
        ]
    )
current_month_name = (
    list(current_model_stats.values())[0]
    ["valid_time"]
    .iloc[0]
    .strftime("%B")
)
#fetch reference running means for current and next month
first_month = (
    list(current_model_stats.values())[0]
    ["valid_time"]
    .iloc[0]
    .month
)
# ---------------------------------------------------------------
# Reference running means
# ---------------------------------------------------------------
reference_current = build_reference_running_mean(
    first_month,
    init_time.year
)
if any(
    not df.empty
    for df in next_model_stats.values()
):
    next_month = (
        list(next_model_stats.values())[0]
        ["valid_time"]
        .iloc[0]
        .month
    )
    reference_next = build_reference_running_mean(
        next_month,
        init_time.year
    )
# rename to match plotting conventions
observed_df = observed_df.rename(
    columns={
        "date": "valid_time",
        "t_raw": "t_raster"
    }
)
# only current month
current_month_start = (
    observed_df["valid_time"]
    .max()
    .normalize()
    .replace(day=1)
)
observed_running = observed_df.loc[
    observed_df["valid_time"] >= current_month_start
].copy()
observed_running["running_mean"] = (
    observed_running["t_raster"]
    .expanding()
    .mean()
)
#call plotting function
make_model_plot(
    current_model_stats,
    current_model_results,
    reference_current,
    observed_running,
    f"{run_string} | Germany | {current_month_name} | 2 m rastered running monthly mean",
    f"forecast_{current_month_name}_{run_string}.png",
    add_observed=(completed_days > 0),  #True
    ytick_interval=0.5
)
if any(
    not df.empty
    for df in next_model_stats.values()
):
    next_month_name = (
        list(next_model_stats.values())[0]
        ["valid_time"]
        .iloc[0]
        .strftime("%B")
    )
    make_model_plot(
        next_model_stats,
        next_model_results,
        reference_next,
        None,
        f"{run_string} | Germany | {next_month_name} | 2 m rastered running mean",
        f"forecast_{next_month_name}_{run_string}.png",
        add_observed=False,
        ytick_interval=1.0
    )
##call plotting function again for second plot based on summer running mean rather than August running mean
#make_model_plot(
#    summer_model_stats,
#    summer_model_results,
#    reference_summer,
#    summer_observed,
#    f"{run_string} | Germany | {current_month_name} | 2 m rastered running mean",
#    f"forecast_season_running_mean_{current_month_name}_{run_string}.png",
#    add_observed=(completed_days > 0),  #True
#    ytick_interval=0.5,
#    running_mean_column="summer_running_mean",
#    reference_running_specific_year_1=reference_summer_specific_year_1,
#    reference_running_specific_year_2=reference_summer_specific_year_2
#)

# =============================================================================
# Publish plots to GitHub
# =============================================================================
print()
print("=" * 70)
print("Publishing forecast plots to GitHub...")
print("=" * 70)
print()

try:
    result = subprocess.run(
        [
            sys.executable,
            "publish2git.py",
            "--date",
            args.date,
            "--run",
            args.run,
        ],
        cwd=PROJECT_DIR,
        check=True,
    )
    print()
    print("=" * 70)
    print("GITHUB PUBLISHING SUCCESS")
    print("=" * 70)
    print(f"Published run: {run_string}")
    print("=" * 70)

except subprocess.CalledProcessError as error:
    print()
    print("=" * 70)
    print("GITHUB PUBLISHING FAILED")
    print("=" * 70)
    print(
        "Forecast processing and plot generation completed successfully,\n"
        "but the plots could not be published to GitHub."
    )
    print(f"Publisher exit code: {error.returncode}")
    print("=" * 70)

# ------------------------------------------------------------------
# Clean up old normalized forecast files
# ------------------------------------------------------------------
import re
from datetime import datetime, timedelta

NC_FILE_AGE_DAYS = 2

cutoff_date = datetime.now().date() - timedelta(days=NC_FILE_AGE_DAYS)

deleted_files = 0

for nc_file in NORMALIZED_DIR.rglob("*.nc"):

    match = re.search(r"_(\d{8})_(\d{2})Z\.nc$", nc_file.name)

    if not match:
        print(f"[CLEANUP] Could not determine run date: {nc_file}")
        continue

    run_date = datetime.strptime(match.group(1), "%Y%m%d").date()

    if run_date <= cutoff_date:
        try:
            nc_file.unlink()
            deleted_files += 1
            print(f"[CLEANUP] Deleted old forecast: {nc_file}")
        except OSError as e:
            print(f"[CLEANUP] Could not delete {nc_file}: {e}")
print(
    f"[CLEANUP] Deleted {deleted_files} normalized forecast files "
    f"from runs on or before {cutoff_date}."
)