import xarray as xr
ds = xr.open_dataset(
    "gep01.t12z.pgrb2a.0p50.f003",
    engine="cfgrib"
)
print(ds)