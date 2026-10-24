# Germany 2 m Temperature Forecasts

Python workflow for producing gridded 2 m air-temperature forecasts over Germany from several numerical weather prediction models. The workflow downloads/reads forecast data, maps it to a common Germany grid, applies elevation/lapse-rate corrections where configured, calculates daily and running means, and creates plots for the current and following month.

## Forecast models

The project has been used with:

- GFS
- IFS
- AIFS
- ICON-EPS

Model availability depends on the downloader configuration and the forecast run being processed.

## Repository layout

```text
.
├── config.py
├── run_processing.py
├── publish2git.py
├── downloaders/
├── preprocessing/
├── processing/
├── utils/
└── Ensembles_outputs/       # Published output folders, organised by run
```

The repository may also contain supporting static-grid files or other configuration assets. Keep any files required by `config.py` and the processing scripts when cloning or deploying the project.

## Requirements

- Linux, macOS, or Windows with WSL2
- Conda or Miniconda
- Network access to the forecast data sources
- Git, if you want to publish generated outputs to GitHub

GRIB-reading dependencies may require ecCodes. The provided `environment.yml` includes `cfgrib` and `eccodes` through Conda-forge.

## Set up the environment

From the repository root:

```bash
conda env create -f environment.yml
conda activate germany-forecast
```

If you already have an environment with the project's dependencies, you can keep using it. To update an existing environment from this file:

```bash
conda env update -f environment.yml --prune
```

The environment file is a portable starting point. If the code imports additional packages or relies on system tools not listed here, add those requirements before recreating the environment on another machine.

## Run processing

Run processing for a forecast initialisation date. The date is passed as `YYYY-MM-DD` or `YYYYMMDD`; the run is `00` or `12` UTC and defaults to `00` if omitted.

```bash
python run_processing.py --date 2026-10-24 --run 00
```

For a compact date:

```bash
python run_processing.py --date 20261024 --run 12
```

Check `python run_processing.py --help` for the options supported by the current version of the script.

Processing expects the forecast input files and static grid/configuration assets to be available at the paths defined in `config.py`. It writes a run-specific output directory, typically named like `YYYYMMDD_HHZ`, and produces the configured plots and data products there.

### Downloading forecast inputs

Downloaders live in `downloaders/`. The project has also been run using a shell wrapper such as `run_forecast.sh` to download model data before calling `run_processing.py`. Inspect the wrapper and downloader command-line help for the exact sequence and options in your checkout. Processing will not be able to create a complete set of plots if required input files have not downloaded successfully.

## Publish outputs to GitHub

`publish2git.py` publishes a processed run to the `Ensembles_outputs/` directory in the configured Git repository. First check the script's configuration and command-line help:

```bash
python publish2git.py --help
```

If the script is configured to publish a specific date and run, use the options shown by `--help`, for example:

```bash
python publish2git.py --date 2026-10-24 --run 00
```

Publishing is separate from processing unless your local version explicitly calls the publishing script automatically. Review the target repository and staged changes before pushing. The publisher has been designed to avoid overwriting an existing run directory; do not remove that safeguard unless you deliberately want different behaviour.

## Configuration and static data

- `config.py` defines project paths and processing settings.
- `downloaders/` contains model-specific input retrieval code.
- `preprocessing/` contains preparation/regridding steps.
- `processing/` contains the forecast calculations and output generation.
- `utils/` contains shared helper functions.
- `Ensembles_outputs/` stores published runs.

Some static assets (for example, a precomputed Germany grid/DEM file and metadata) may be required but can be too large or project-specific to include automatically. Confirm that all paths referenced by `config.py` exist before running the pipeline. Do not commit downloaded forecast caches, temporary GRIB index files, logs, credentials, or large generated files unless they are intentionally part of the project.

## Typical workflow

1. Download the required model data using the project's downloader scripts or shell wrapper.
2. Run `run_processing.py` for the chosen date and UTC run.
3. Inspect the generated plots and data products.
4. Publish the run with `publish2git.py` if desired.
5. Check the Git diff/status and push the intended changes to GitHub.

## Reproducibility notes

Forecast-provider endpoints, model availability, and upstream data formats can change. Keep the code, environment file, and configuration in sync, and record any additional external requirements needed to reproduce a run.
