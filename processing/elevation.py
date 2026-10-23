import numpy as np
from scipy.interpolate import RegularGridInterpolator
from processing.static_grid import load_static_grid

#Cache so the DEM is only loaded/interpolated once per Python session
_DEM_INTERPOLATOR = None

def _get_dem_interpolator():
    """
    Build an interpolator for the static Germany DEM.

    Returns
    -------
    scipy.interpolate.RegularGridInterpolator
    """

    global _DEM_INTERPOLATOR

    if _DEM_INTERPOLATOR is not None:
        return _DEM_INTERPOLATOR

    static = load_static_grid()

    grid_lat = static["grid_lat"]
    grid_lon = static["grid_lon"]
    dem = static["DEM_grid"]

    # RegularGridInterpolator expects 1D coordinates
    lat = grid_lat[:, 0]
    lon = grid_lon[0, :]

    # Ensure increasing coordinates
    if lat[0] > lat[-1]:
        lat = lat[::-1]
        dem = dem[::-1, :]

    if lon[0] > lon[-1]:
        lon = lon[::-1]
        dem = dem[:, ::-1]

    _DEM_INTERPOLATOR = RegularGridInterpolator(
        (lat, lon),
        dem,
        bounds_error=False,
        fill_value=np.nan,
    )
    return _DEM_INTERPOLATOR

def build_model_elevation(latitude, longitude):
    """
    Interpolate the Germany DEM onto an arbitrary forecast model grid.

    Parameters
    ----------
    latitude : ndarray
        Model latitude grid (2D).

    longitude : ndarray
        Model longitude grid (2D).

    Returns
    -------
    ndarray
        DEM elevation on the model grid (metres).
    """

    interpolator = _get_dem_interpolator()
    
    points = np.column_stack(
        (
            latitude.ravel(),
            longitude.ravel()
        )
    )

    elevation = interpolator(points)

    return elevation.reshape(latitude.shape)