from pathlib import Path
# =============================================================================
# Directories
# =============================================================================
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
FORECAST_DIR = DATA_DIR / "forecasts"
DEM_DIR = DATA_DIR / "eudem"
STATIC_DIR = DATA_DIR / "static"
GERMANY_DIR = DATA_DIR / "Germany"
NORMALIZED_DIR = DATA_DIR / "normalized"
RESULT_DIR = PROJECT_DIR / "outputs"
TEXT_DIR = RESULT_DIR / "txt"
FIGURE_DIR = RESULT_DIR / "figures"
TMP_DIR = DATA_DIR / "temporary"
STATIC_GRID_FILE = STATIC_DIR / "Germany_static_grid.npz"
STATIC_METADATA_FILE = STATIC_DIR / "grid_metadata.json"
INTERP_CACHE_DIR = STATIC_DIR / "interp_cache"
# =============================================================================
# GitHub
# =============================================================================
GITHUB_DIR = PROJECT_DIR.parent / "github_repo"
GITHUB_OUTPUT_DIR = GITHUB_DIR / "Ensembles_outputs"
#create all directories
DIRECTORIES = [
    DATA_DIR,
    FORECAST_DIR,
    STATIC_DIR,
    NORMALIZED_DIR,
    RESULT_DIR,
    TEXT_DIR,
    FIGURE_DIR,
    TMP_DIR,
    INTERP_CACHE_DIR,
    GITHUB_DIR,
    GITHUB_OUTPUT_DIR
]
for directory in DIRECTORIES:
    directory.mkdir(parents=True, exist_ok=True)
# =============================================================================
# Germany bounding box
# =============================================================================
LAT_MIN = 47.0
LAT_MAX = 55.5
LON_MIN = 5.5
LON_MAX = 15.5
# =============================================================================
# Raster grid
# =============================================================================
GRID_RESOLUTION = 0.01
# =============================================================================
# Projection
# =============================================================================
INIT_PROJECTION = "EPSG:4326"
PROJECTION = "EPSG:3035"
# =============================================================================
# Interpolation
# =============================================================================
K_NEIGHBOURS = 25
MAX_DISTANCE = 120000.0
# =============================================================================
# FILES
# =============================================================================
DEM_NODATA = -1e10
SHAPEFILE = GERMANY_DIR / "ne_110m_admin_0_countries.shp"
LAPSE_RATE_FILE = (DATA_DIR / "lapse_rates" / "monthly_lapse_rates_2026.txt")
MONTHLY_MEAN_FILE = (DATA_DIR / "current_monthly_means" / "DWD_monthly_raster_sta25_dist120000.000_EPSG3035_2026-2027.txt")
CURRENT_DAILY_MEAN_FILE = (DATA_DIR / "current_monthly_means" / "DWD_daily_raster_sta25_dist120000.000_EPSG3035_2026-2027.txt")
# =============================================================================
# FORECAST MODELS
# =============================================================================
MODELS = {
    "GFS": {"grid": "regular", "oper": "GFS", "control": "C00", "ensemble": "GEFS"},
    "IFS": {"grid": "regular", "oper": "HRES", "control": None, "ensemble": "ENS_ECMWF"},
    "AIFS": {"grid": "regular", "oper": "AIFS", "control": None, "ensemble": "ENS_AIFS"},
    "GEM": {"grid": "regular", "oper": "GEM", "control": None, "ensemble": None},
    "ICON_EU": {"grid": "icon", "oper": "ICON_EU", "control": None, "ensemble": "ENS_ICON_EU"},  #
    "ICON_D2": {"grid": "icon", "oper": "ICON_D2", "control": None, "ensemble": None},
}
ENSEMBLE_MEMBERS = {
    "GEFS": [
        "GFS",
        "C00",
        *[f"P{i:02d}" for i in range(1, 31)],
    ],
    "ENS_ECMWF": [
        "HRES",
        *[f"P{i:02d}" for i in range(1, 51)],
    ],
    "ENS_AIFS": [
        "AIFS", 
        *[f"P{i:02d}" for i in range(1, 51)],
    ],
    "ENS_ICON_EU": [
        "ICON_EU",
        *[f"P{i:02d}" for i in range(1,41)],
    ]
}
