import numpy as np
from scipy.spatial import cKDTree
from pathlib import Path
import joblib
from config import INTERP_CACHE_DIR, K_NEIGHBOURS
from processing.forecast_reader import Forecast  # we will reuse later

def build_cache(model_name, model_lats, model_lons, germany_coords):

    Path(INTERP_CACHE_DIR).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. project model grid into same coordinate system as Germany grid
    # ------------------------------------------------------------------
    from pyproj import Transformer

    transformer = Transformer.from_crs(
        INIT_PROJECTION,
        PROJECTION,
        always_xy=True
    )
    mx, my = transformer.transform(
        model_lons.ravel(),
        model_lats.ravel()
    )
    model_coords = np.column_stack([mx, my])
    # ------------------------------------------------------------------
    # 2. build KDTree ONCE
    # ------------------------------------------------------------------
    tree = cKDTree(model_coords)
    # ------------------------------------------------------------------
    # 3. query nearest neighbors for every Germany grid point
    # ------------------------------------------------------------------
    dist, idx = tree.query(
        germany_coords,
        k=K_NEIGHBOURS
    )
    # ------------------------------------------------------------------
    # 4. save cache
    # ------------------------------------------------------------------
    cache_file = INTERP_CACHE_DIR / f"{model_name}_interp_cache.pkl"
    joblib.dump(
        {
            "indices": idx,
            "distances": dist,
            "model_coords": model_coords
        },
        cache_file
    )
    print(f"[OK] Saved interpolation cache for {model_name}")