import os
from datetime import datetime, timedelta
import xarray as xr
import cfgrib
import requests
from pathlib import Path

from config import FORECAST_DIR


BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod"


def build_url(run_date, hour="00", fhr=0):

    date_str = run_date.strftime("%Y%m%d")
    return (
        f"{BASE_URL}/gfs.{date_str}/{hour}/atmos/"
        f"gfs.t{hour}z.pgrb2.0p25.f{str(fhr).zfill(3)}"
    )


def download_file(url, out_path):
    r = requests.get(url, stream=True)
    if r.status_code != 200:
        raise RuntimeError(f"Failed download {url}")
    with open(out_path, "wb") as f:
        f.write(r.content)


def process_grib(grib_file):

    ds = xr.open_dataset(
        grib_file,
        engine="cfgrib"
    )
    # select 2m temperature
    t2m = ds["t2m"] - 273.15  # convert K → °C
    return ds, t2m


def download_gfs(run_date=None, hour="00", max_fhr=120):

    if run_date is None:
        run_date = datetime.utcnow()

    model_dir = FORECAST_DIR / "GFS"
    model_dir.mkdir(parents=True, exist_ok=True)

    all_data = []

    for fhr in range(0, max_fhr + 1, 3):

        url = build_url(run_date, hour, fhr)

        file_path = model_dir / f"gfs_f{str(fhr).zfill(3)}.grib2"

        print(f"Downloading {url}")

        try:
            download_file(url, file_path)

            ds, t2m = process_grib(file_path)

            all_data.append(t2m)

        except Exception as e:
            print("skip:", e)
            continue

    # merge into time series
    combined = xr.concat(all_data, dim="time")

    out_file = model_dir / "latest.nc"
    combined.to_netcdf(out_file)

    print(f"[OK] GFS saved → {out_file}")

    return out_file