import json
import numpy as np
from config import STATIC_GRID_FILE, STATIC_METADATA_FILE

def load_static_grid():
    """
    Load the precomputed Germany static grid.
    """
    data = np.load(STATIC_GRID_FILE)

    static = {
        "grid_lon": data["grid_lon"],
        "grid_lat": data["grid_lat"],
        "germany_mask": data["germany_mask"],
        "DEM_grid": data["DEM_grid"],
        "projected_coords": data["projected_coords"],
        "target_points": data["target_points"]
    }
    return static

def load_static_metadata():
    """
    Load metadata describing the Germany grid.
    """
    with open(STATIC_METADATA_FILE, "r") as f:
        metadata = json.load(f)

    return metadata