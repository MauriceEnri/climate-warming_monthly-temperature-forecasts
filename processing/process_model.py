import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from processing.static_grid import load_static_grid
from processing.lapse_rate import load_monthly_lapse_rates, get_lapse_rate
from processing.interpolator import interpolate_forecast
from config import RESULT_DIR
from config import CURRENT_DAILY_MEAN_FILE

def process_model(
        model_name,
        forecast_file,
        member
):
    """
    Process one forecast model.

    Parameters
    ----------
    model_name : str

    forecast_file : Path
        Normalized NetCDF produced by normalize_forecast()

    Returns
    -------
    pandas.DataFrame
    """
    #load grid space
    static = load_static_grid()
    grid_lon = static["grid_lon"]
    grid_lat = static["grid_lat"]
    germany_mask = static["germany_mask"]

    DEM_grid = static["DEM_grid"]

    #grab monthly lapse rates
    monthly_slopes = load_monthly_lapse_rates()

    #open forecast
    ds = xr.open_dataset(forecast_file)
    #find starting time
    init_time = pd.Timestamp(ds.attrs["init_time"])
    #extract model run time
    run_string = init_time.strftime("%Y%m%d_%HZ")

    #fetch observed rastered mean for current day 
    today_raster_mean=None
    if CURRENT_DAILY_MEAN_FILE.exists():
        daily_obs = pd.read_csv(
            CURRENT_DAILY_MEAN_FILE,
            parse_dates=["date"]
        )
        forecast_day = init_time.normalize()
        row = daily_obs.loc[
            daily_obs["date"] == forecast_day
        ]
        if not row.empty:
            today_raster_mean = row.iloc[0]["t_raw"]
    #print("Forecast day:", forecast_day)
    #print("Available dates:")
    #print(daily_obs["date"].head())
    #print("Matched rows:", len(row))
    #print("today_raster_mean:", today_raster_mean)
    #initialise results
    results = []
    #initialise rasters
    rasters = []
    #loop over forecast times
    for t in ds.time:
        valid_time = pd.Timestamp(
            t.values
        )
        lead_time_days = (valid_time - init_time).total_seconds() / 86400.0
        lead_time_hours = (valid_time - init_time).total_seconds() / 3600.0
        #monthly lapse rates
        slope = get_lapse_rate(
            monthly_slopes,
            valid_time
        )
        #temperature field
        temperature = ds.temperature.sel(
            time=t
        ).values
        #model elevation
        model_elevation = ds.model_elevation.values
        #reduce to sea level
        T_sea = (
            temperature
            - slope * model_elevation
        )
        if model_name == "ICON_EU":
            temp_ds = xr.Dataset(
                data_vars={
                    "temperature": (
                        ("point",),
                        T_sea
                    )
                },
                coords={
                    "lat": ("point", ds.lat.values),
                    "lon": ("point", ds.lon.values),
                }
            )
        else:
            temp_ds = xr.Dataset(
                data_vars={
                    "temperature": (
                        ("y", "x"),
                        T_sea
                    )
                },
                coords={
                    "lat": (
                        ("y", "x"),
                        ds.lat.values
                    ),
                    "lon": (
                        ("y", "x"),
                        ds.lon.values
                    )
                }
            )
        #interpolate
        grid_T_sea = interpolate_forecast(
            temp_ds,
            model_name,
            grid_lat,
            grid_lon
        )
        #Add DEM correction
        grid_T = (
            grid_T_sea
            + slope * DEM_grid
        )
        #mask for area of interest
        grid_T = np.where(
            germany_mask,
            grid_T,
            np.nan
        )
        #raster mean
        raster_mean = np.nanmean(
            grid_T
        )
        #number of contributing grid cells
        n_grid = np.sum(
            ~np.isnan(grid_T)
        )
        #store results 
        results.append({
            "valid_time": valid_time,
            "init_time": init_time,
            "run_string": run_string,
            "model": model_name,
            "member": member,
            "lead_time_days": lead_time_days,
            "lead_time_hours": lead_time_hours,
            "t_raster": raster_mean,
            "n_grid_points": n_grid
        })
        rasters.append(grid_T.copy())
    #convert to DataFrame
    results_df = pd.DataFrame(results)
    #return sorted results_df
    results_df = results_df.sort_values("lead_time_days")
    results_df = (
        results_df
        .sort_values("valid_time")
        .reset_index(drop=True)
    )
    #print("\n\n\n\n", results_df[["valid_time", "t_raster"]].head(20))
    #print("\n\n\n\n", results_df.groupby(results_df["valid_time"].dt.normalize()).size())
    #get daily running means
    daily_df = (
        results_df
        .groupby(results_df["valid_time"].dt.normalize(), as_index=False)
        .agg(
            t_raster=("t_raster", "mean"),
            n_grid_points=("n_grid_points", "mean")
        )
    )
    daily_df = daily_df.rename(columns={"valid_time": "valid_time"})
    #print("\n\n\n\n", daily_df)
    # restore metadata after aggregation
    daily_df["model"] = model_name
    daily_df["member"] = member
    daily_df["init_time"] = init_time
    daily_df["run_string"] = run_string
    # -------- hybrid first forecast day consisting of observed and forecast data --------
    if today_raster_mean is not None:
        forecast_start = pd.Timestamp(init_time)
        day_start = (
            daily_df.loc[0, "valid_time"]
            .normalize()
        )
        day_end = (
            day_start
            +
            pd.Timedelta(days=1)
        )
        observed_hours = (
            forecast_start - day_start
        ).total_seconds() / 3600.0
        #keep within valid range
        observed_hours = np.clip(
            observed_hours,
            0,
            24
        )
        weighted_sum = (
            observed_hours
            *
            today_raster_mean
        )
        #get spacing between forecast hours
        times = results_df["valid_time"].to_numpy()

        interval_hours = np.empty(len(times))

        for i in range(len(times) - 1):
            interval_hours[i] = (
                times[i + 1] - times[i]
            ) / np.timedelta64(1, "h")

        # last timestep: assume same spacing as previous
        interval_hours[-1] = interval_hours[-2]
        # Add remaining forecast periods
        for idx, row in results_df.iterrows():

            valid = row["valid_time"]
            # forecast value represents the following 6-hour period
            interval_start = valid
            interval_end = (
                valid +
                pd.Timedelta(hours=interval_hours[idx])
            )
            #only count forecast after current time
            overlap_start = max(
                interval_start,
                forecast_start
            )
            #do not go beyond midnight
            overlap_end = min(
                interval_end,
                day_end
            )
            overlap_hours = (
                overlap_end - overlap_start
            ).total_seconds() / 3600.0

            if overlap_hours > 0:
                weighted_sum += (
                    overlap_hours
                    *
                    row["t_raster"]
                )
        daily_df.loc[0, "t_raster"] = (
            weighted_sum / 24.0
        )
        #print("init_time: \n", init_time)
        #print("First daily mean: \n", daily_df.loc[0, "t_raster"])
    daily_df["lead_day"] = np.arange(1, len(daily_df) + 1)
    #retain the lead time in the daily output
    daily_df["lead_time_days"] = daily_df["lead_day"] - 1
    #produce running means
    daily_df["running_mean"] = (
        daily_df["t_raster"]
        .expanding()
        .mean()
    )
    return daily_df, init_time

    ##assign each daily mean to midnight of its corresponding date
    #daily_df["valid_time"] = (
    #    pd.to_datetime(daily_df["valid_time"])
    #    .dt.normalize()
    #)
    #for _, row in daily_df.iterrows():
    #    print(
    #        row["valid_time"],
    #        row["t_raster"]
    #    )
    #print(results_df[
    #    ["valid_time", "lead_time_hours", "lead_time_days", "t_raster"]
    #].head(12))
    #print(
    #        valid_time,
    #       "raw model mean:",
    #        np.nanmean(temperature)
    #    )
    #print(
    #        valid_time,
    #        "raster mean:",
    #        raster_mean
    #    )
    #print(
    #        "FORECAST TIME:",
    #        valid_time,
    #        "LEAD HOURS:",
    #        (valid_time - init_time).total_seconds()/3600
    #    )

    ##get calender day means independent of starting hour of forecast model run
    #if init_time.hour == 6:
    #    duplicate = results_df[
    #        results_df["valid_time"].dt.hour.isin([0])
    #    ].copy()
    #
    #    duplicate["valid_time"] -= pd.Timedelta(days=1)
    #
    #    results_df = pd.concat(
    #        [results_df, duplicate],
    #        ignore_index=True
    #    )
    #if init_time.hour == 12:
    #    duplicate = results_df[
    #        results_df["valid_time"].dt.hour.isin([0, 6])
    #    ].copy()
    #
    #    duplicate["valid_time"] -= pd.Timedelta(days=1)
    #
    #    results_df = pd.concat(
    #        [results_df, duplicate],
    #        ignore_index=True
    #    )
    #if init_time.hour == 18:
    #    duplicate = results_df[
    #        results_df["valid_time"].dt.hour.isin([0, 6, 12])
    #    ].copy()
    #
    #    duplicate["valid_time"] -= pd.Timedelta(days=1)
    #
    #    results_df = pd.concat(
    #        [results_df, duplicate],
    #        ignore_index=True
    #    )
    ##sort again after inserting duplicated rows to fill 1st forecast day if not looking at 00Z
    #results_df = (
    #    results_df
    #    .sort_values("valid_time")
    #    .reset_index(drop=True)
    #)

