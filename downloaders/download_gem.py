import xarray as xr
import requests
from pathlib import Path
from config import FORECAST_DIR
from processing.normalise_forecast import normalise_and_save

BASE = "https://dd.weather.gc.ca/model_gem_global/25km/grib2/lat_lon/"

def download_gem():

    model_dir = FORECAST_DIR / "GEM"
    model_dir.mkdir(parents=True, exist_ok=True)

    # simplified: latest directory listing
    r = requests.get(BASE)

    files = [line for line in r.text.split("\n") if "TMP_TGL_2" in line]

    ds_list = []

    for f in files[:30]:

        url = BASE + f

        file_path = model_dir / f.split("/")[-1]

        r = requests.get(url)

        with open(file_path, "wb") as out:
            out.write(r.content)

        ds = xr.open_dataset(file_path, engine="cfgrib")

        ds_list.append(ds["t2m"] - 273.15)

    combined = xr.concat(ds_list, dim="time")

    out = model_dir / "latest.nc"
    combined.to_netcdf(out)

    print("[OK] GEM saved")

    return out

normalise_and_save(
    grib_file=file_path,
    output_file=model_dir / "latest.nc"
)