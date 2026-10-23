import xarray as xr

def open_grib(filename, filter_by_keys=None):
    """
    Open a GRIB file using cfgrib.

    Parameters
    ----------
    filename : str or Path
        GRIB file.
    filter_by_keys : dict, optional
        cfgrib filter (e.g. {"typeOfLevel": "heightAboveGround", "level": 2})

    Returns
    -------
    xarray.Dataset
    """

    backend_kwargs = {}

    if filter_by_keys is not None:
        backend_kwargs["filter_by_keys"] = filter_by_keys

    ds = xr.open_dataset(
        filename,
        engine="cfgrib",
        backend_kwargs=backend_kwargs
    )
    return ds