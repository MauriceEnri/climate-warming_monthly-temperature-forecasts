from pathlib import Path
import xarray as xr

def save_dataset(ds, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path)

def open_dataset(path):
    return xr.open_dataset(path)