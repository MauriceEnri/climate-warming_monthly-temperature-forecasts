import numpy as np
import geopandas as gpd
from shapely.geometry import Point
import rasterio
from pyproj import Transformer
import json
from pathlib import Path
from config import STATIC_DIR

Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)

from config import (
    LON_MIN,
    LON_MAX,
    LAT_MIN,
    LAT_MAX,
    GRID_RESOLUTION,
    INIT_PROJECTION,
    PROJECTION,
    GERMANY_DIR,
    DEM_DIR,
    SHAPEFILE,
    STATIC_GRID_FILE,
    STATIC_METADATA_FILE,
)

lons = np.arange(LON_MIN, LON_MAX, GRID_RESOLUTION)
lats = np.arange(LAT_MIN, LAT_MAX, GRID_RESOLUTION)
#generate all grid points
grid_lon, grid_lat = np.meshgrid(lons, lats)
#==========================================================================
#prepare germany mask
#==========================================================================
# select polygon covering Germany
world = gpd.read_file(SHAPEFILE)
germany = world[world["ADMIN"] == "Germany"]
# build points
points = gpd.GeoDataFrame(
    geometry=[
        Point(lon, lat)
        for lon, lat in zip(grid_lon.ravel(), grid_lat.ravel())
    ],
    crs=INIT_PROJECTION
)
# determine which grid cells lie inside Germany
inside_germany = points.within(germany.geometry.iloc[0])
# reshape to same shape as grid
germany_mask = inside_germany.values.reshape(grid_lon.shape)
print("\nCells inside Germany:\n", np.sum(germany_mask))
#==========================================================================
#coordinate projection
#==========================================================================
transformer = Transformer.from_crs(
    INIT_PROJECTION,
    PROJECTION,
    always_xy=True
)
x, y = transformer.transform(
    grid_lon.ravel(),
    grid_lat.ravel()
)
projected_coords = np.column_stack([x, y])  # EPSG:3035 (metres)
target_points = np.column_stack([  # EPSG:4326 (lat/lon)
    grid_lat.ravel(),
    grid_lon.ravel()
])
#==========================================================================
#SAMPLE DEM AT EVERY GRID POINT
#==========================================================================
tif_files = sorted(DEM_DIR.glob("*.tif"))
src_files = [rasterio.open(fp) for fp in tif_files]

DEM_values = np.full(len(projected_coords), np.nan)

for ds in src_files:

    bounds = ds.bounds

    inside = [
        (i, (px, py))
        for i, (px, py) in enumerate(projected_coords)
        if (
            bounds.left <= px <= bounds.right
            and
            bounds.bottom <= py <= bounds.top
        )
    ]

    if not inside:
        continue

    idxs, pts = zip(*inside)

    values = list(ds.sample(pts))

    for i, val in zip(idxs, values):
        DEM_values[i] = val[0]

DEM_grid = DEM_values.reshape(grid_lon.shape)

DEM_grid = DEM_grid.astype(float)

DEM_grid[DEM_grid < -1e10] = np.nan
#==========================================================================
#SAVE ALL RESULTS
#==========================================================================
np.savez_compressed(
    STATIC_GRID_FILE,
    grid_lon=grid_lon,
    grid_lat=grid_lat,
    germany_mask=germany_mask,
    DEM_grid=DEM_grid,
    projected_coords=projected_coords,
    target_points=target_points
)
#==========================================================================
#SAVE METADATA
#==========================================================================
metadata = {
    "projection": PROJECTION,
    "grid_resolution": GRID_RESOLUTION,
    "lon_min": LON_MIN,
    "lon_max": LON_MAX,
    "lat_min": LAT_MIN,
    "lat_max": LAT_MAX,
    "rows": grid_lon.shape[0],
    "columns": grid_lon.shape[1],
    "n_cells": grid_lon.size,
    "n_cells_germany": int(np.sum(germany_mask))
}
with open(STATIC_METADATA_FILE, "w") as f:
    json.dump(metadata, f, indent=4)