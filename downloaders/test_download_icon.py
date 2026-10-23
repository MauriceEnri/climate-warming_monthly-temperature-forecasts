import xarray as xr

ds_temp = xr.open_dataset("icon-eps_global_icosahedral_single-level_2026080312_020_t_2m.grib2", engine="cfgrib")
ds_lat = xr.open_dataset("icon-eps_global_icosahedral_time-invariant_2026080312_clat.grib2", engine="cfgrib")
ds_lon = xr.open_dataset("icon-eps_global_icosahedral_time-invariant_2026080312_clon.grib2", engine="cfgrib")
print(ds_lat["tlat"].min().values, ds_lat["tlat"].max().values)
print(ds_lon["tlon"].min().values, ds_lon["tlon"].max().values)
print(ds_temp.t2m.shape)
print(ds_lat.tlat.shape)
print(ds_lon.tlon.shape)