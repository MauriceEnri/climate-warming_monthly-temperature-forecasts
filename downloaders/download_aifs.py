import cdsapi
import xarray as xr
from pathlib import Path
from config import FORECAST_DIR
from processing.normalise_forecast import normalise_and_save

def download_aifs():

    model_dir = FORECAST_DIR / "IFS"
    model_dir.mkdir(parents=True, exist_ok=True)

    c = cdsapi.Client()

    out_file = model_dir / "ifs.grib"

    c.retrieve(
        "reanalysis-era5-single-levels",  # placeholder dataset
        {
            "variable": "2m_temperature",
            "product_type": "forecast",
            "format": "grib",
        },
        str(out_file),
    )

    ds = xr.open_dataset(out_file, engine="cfgrib")

    ds["t2m"].to_netcdf(model_dir / "latest.nc")

    print("[OK] AIFS saved")

    return model_dir / "latest.nc"

normalise_and_save(
    grib_file=file_path,
    output_file=model_dir / "latest.nc"
)