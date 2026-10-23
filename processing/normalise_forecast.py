import numpy as np
import pandas as pd
import xarray as xr
from processing.elevation import build_model_elevation

def normalize_forecast(
    temperature,
    latitude,
    longitude,
    valid_times,
    init_time,
    model_name
):
    """
    Build a standardized forecast Dataset.

    Parameters
    ----------
    temperature : ndarray
        Temperature in °C.
        Regular grids: (time, y, x) or (y, x)
        ICON unstructured grid: (time, points) or (points,)
    latitude : ndarray
        Shape (y, x)
    longitude : ndarray
        Shape (y, x)
    elevation : ndarray
        Shape (y, x), metres
    valid_times : sequence
        Forecast valid times
    init_time : datetime-like
        Model initialization time
    model_name : str

    Returns
    -------
    xarray.Dataset
    """
    # ---------------------------------------------------------
    # Handle model grids
    # ---------------------------------------------------------

    # ICON unstructured grid:
    # latitude and longitude are both 1D arrays of identical length
    if (
        latitude.ndim == 1
        and longitude.ndim == 1
        and len(latitude) == len(longitude)
    ):
        print("Detected ICON unstructured grid")

    # Regular lat/lon grid:
    # latitude and longitude are separate coordinate vectors
    elif (
        latitude.ndim == 1
        and longitude.ndim == 1
    ):
        print("Detected regular lat/lon grid")

        longitude, latitude = np.meshgrid(
            longitude,
            latitude
        )
    # Already gridded
    elif (
        latitude.ndim == 2
        and longitude.ndim == 2
    ):
        pass
    else:
        raise ValueError(
            f"Unsupported coordinate dimensions: "
            f"{latitude.shape}, {longitude.shape}"
        )
    print(f"Interpolating DEM to {model_name} grid...")

    elevation = build_model_elevation(
        latitude,
        longitude
    )
    # Structured grid (GFS, IFS, AIFS)
    if latitude.ndim == 2:

        ds = xr.Dataset(
            data_vars={
                "temperature": (
                    ("time", "y", "x"),
                    temperature
                ),
                "model_elevation": (
                    ("y", "x"),
                    elevation
                ),
            },
            coords={
                "time": valid_times,
                "y": np.arange(latitude.shape[0]),
                "x": np.arange(latitude.shape[1]),
                "lat": (("y", "x"), latitude),
                "lon": (("y", "x"), longitude),
            },
            attrs={
                "model": model_name,
                "init_time": pd.Timestamp(init_time).isoformat()
            }
        )
    #Unstructured grid (ICON-EU)
    else:
        ds = xr.Dataset(
            data_vars={
                "temperature": (
                    ("time", "point"),
                    temperature
                ),
                "model_elevation": (
                    ("point",),
                    elevation
                ),
            },
            coords={
                "time": valid_times,
                "point": np.arange(len(latitude)),
                "lat": ("point", latitude),
                "lon": ("point", longitude),
            },
            attrs={
                "model": model_name,
                "init_time": pd.Timestamp(init_time).isoformat()
            }
        )
    return ds