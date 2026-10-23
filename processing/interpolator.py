import numpy as np
from scipy.interpolate import (
    RegularGridInterpolator,
    griddata
)
from config import MODELS
from scipy.spatial import Delaunay
from scipy.interpolate import LinearNDInterpolator

#prepare ICON Cache for the unregular ICON grid
_ICON_INTERPOLATOR_CACHE = {}

def _interpolate_regular(
        temperature,
        lat2d,
        lon2d,
        target_lat,
        target_lon
):
    """
    Interpolate a regular latitude-longitude grid onto the
    Germany target raster.
    """
    lat = lat2d[:, 0]
    lon = lon2d[0, :]
    # RegularGridInterpolator requires increasing coordinates
    if lat[0] > lat[-1]:
        lat = lat[::-1]
        temperature = temperature[::-1, :]
    if lon[0] > lon[-1]:
        lon = lon[::-1]
        temperature = temperature[:, ::-1]
    interpolator = RegularGridInterpolator(
        (lat, lon),
        temperature,
        bounds_error=False,
        fill_value=np.nan
    )
    points = np.column_stack(
        (
            target_lat.ravel(),
            target_lon.ravel()
        )
    )
    result = interpolator(points)

    return result.reshape(target_lat.shape)

def _interpolate_icon(
    temperature,
    lat,
    lon,
    target_lat,
    target_lon,
):
    """
    Interpolate ICON unstructured grid using a cached triangulation.
    """
    key = (lat.shape, lon.shape)

    if key not in _ICON_INTERPOLATOR_CACHE:

        print("Building ICON triangulation...")

        points = np.column_stack((lat, lon))

        tri = Delaunay(points)

        _ICON_INTERPOLATOR_CACHE[key] = (
            tri,
            np.column_stack(
                (
                    target_lat.ravel(),
                    target_lon.ravel(),
                )
            ),
        )
    tri, target_points = _ICON_INTERPOLATOR_CACHE[key]

    interpolator = LinearNDInterpolator(
        tri,
        temperature,
        fill_value=np.nan,
    )
    result = interpolator(target_points)

    return result.reshape(target_lat.shape)

def interpolate_forecast(
        ds,
        model,
        target_lat,
        target_lon,
        variable="temperature"
):
    """
    Interpolate one forecast field to the Germany raster.

    Parameters
    ----------
    ds : xarray.Dataset
        Normalized forecast dataset.
    model : str
        Model name (GFS, IFS, ICON_EU, ...)
    target_lat, target_lon : ndarray
        Germany raster coordinates.
    variable : str
        Dataset variable to interpolate.
    Returns
    -------
    ndarray
    """
    model_info = MODELS[model]

    temperature = ds[variable].values

    lat = ds["lat"].values
    lon = ds["lon"].values

    if model_info["grid"] == "regular":
        return _interpolate_regular(
            temperature,
            lat,
            lon,
            target_lat,
            target_lon
        )
    elif model_info["grid"] == "icon":
        return _interpolate_icon(
            temperature,
            lat,
            lon,
            target_lat,
            target_lon
        )
    else:
        raise ValueError(
            f"Unknown grid type for model {model}"
        )