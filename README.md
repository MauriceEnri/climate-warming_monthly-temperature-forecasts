# Germany 2 m Temperature Forecasts

This project automates the production of gridded 2 m air-temperature forecasts over Germany. It downloads available forecast data, prepares the model fields, applies the configured grid/elevation and lapse-rate processing, calculates daily and running means, creates plots for the **current and following month when data are available**, and can publish the results to GitHub.

The main entry point is `run_forecast.sh`. It is designed to run the full pipeline for the **00Z** or **12Z** forecast cycle and is suitable for scheduled execution with `cron`.

## Forecast models and data sources

The links below point to the providers' model data or documentation. The models actually downloaded during a run depend on the downloader scripts and their current configuration; consult `downloaders/` and `config.py` for the exact implementation and paths.

| Model | Provider | Data / documentation |
|---|---|---|
| GFS — Global Forecast System | NOAA / NCEP | [GFS data and access options](https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast) · [NOAA GFS products](https://vlab.noaa.gov/web/gfs/products) |
| IFS — Integrated Forecasting System | ECMWF | [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) · [Open Data technical documentation](https://confluence.ecmwf.int/pages/viewpage.action?pageId=394991621) |
| AIFS — Artificial Intelligence Forecasting System | ECMWF | [AIFS data](https://www.ecmwf.int/en/forecasts/datasets/aifs-machine-learning-data) · [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) |
| ICON-EU | Deutscher Wetterdienst (DWD) | [DWD NWP Open Data directory](https://opendata.dwd.de/weather/nwp/) · [ICON-EU data directory](https://opendata.dwd.de/weather/nwp/icon-eu/) |

Forecast-provider endpoints, file layouts, and model versions can change. Use the current provider documentation if a downloader URL stops working. DWD is also updating its NWP open-data directory layout, so check the DWD index if a model URL changes.

## Project structure

```text
forecast_rastered/
├── config.py
├── run_forecast.sh
├── run_processing.py
├── publish2git.py
├── downloaders/
├── preprocessing/
├── processing/
├── utils/
├── data/
└── logs/
```

- **`config.py`** — central configuration for project paths, model inputs, the Germany grid, static assets, and other processing settings. Read this file before moving the project or changing its directory layout.
- **`run_forecast.sh`** — orchestrates the end-to-end scheduled workflow.
- **`downloaders/`** — scripts that retrieve forecast model data.
- **`preprocessing/`** — preparation and regridding steps.
- **`processing/`** — raster calculations, running means, and plot generation.
- **`publish2git.py`** — publishes processed outputs to the configured Git repository.
- **`data/`** — generated and supporting data, including subfolders containing the Germany grid and other assets required by the workflow. The exact files and paths are documented in `config.py`. Avoid deleting or moving these files without updating the configuration.
- **`logs/`** — run-specific log directories. Each run stores logs from the individual downloader scripts and the DWD update process in its own subfolder.

Published plots are stored in the repository's `Ensembles_outputs/` directory, organised by forecast run (for example, `Ensembles_outputs/YYYYMMDD_00Z/`). The exact output paths are controlled by the configuration and publishing script.

## How the full pipeline works

`run_forecast.sh` is the recommended entry point when you want the whole workflow to run in one go. The script coordinates the steps configured in the project, including:

1. Updating the relevant DWD station/climate data used by the workflow.
2. Downloading available forecast data with the model-specific downloader scripts.
3. Processing the forecast fields onto the Germany grid.
4. Calculating the configured daily and running-mean products.
5. Creating plots for the current and following month when the required data are available.
6. Publishing the generated run outputs to the configured GitHub repository, if publishing is enabled in the script/configuration.

The script may skip products when data are unavailable or a downloader fails. Check the run-specific files under `logs/` to diagnose an incomplete run.

## Run the pipeline manually

Activate the Conda environment first (see below), then run from the project directory:

```bash
cd /path/to/forecast_rastered
chmod +x run_forecast.sh   # only needed if the script is not executable
./run_forecast.sh 00
```

For the 12Z cycle:

```bash
./run_forecast.sh 12
```
For the 12Z cycle, the temperature mean of the current day is build from already available observed from DWD as well as the forecast time stamps covering the remainder of the current day. For this purpose, a separate script `run_dwd_12Z.sh` is run just after 12 UTC to grab the temperature mean from the first half of the day, before the second half is made up of the forecast data starting at 12Z.

The argument selects the forecast initialisation cycle. Check the shell script itself if you need to confirm the supported arguments or change its behaviour.

You can also run the processing step separately when the required inputs have already been downloaded:

```bash
python run_processing.py --date YYYY-MM-DD --run 00
```

Use `python run_processing.py --help` to check the options supported by the current version. Running `run_processing.py` alone does not necessarily perform the DWD update, downloads, or GitHub publishing; use `run_forecast.sh` for the complete pipeline.

## Schedule automatic runs with cron

The pipeline can be run automatically using `cron`. The existing schedule used for this project is:

- **08:15 local machine time** — run the 00Z forecast cycle at GMT time zone.
- **20:15 local machine time** — run the 12Z forecast cycle at GMT time zone.

Edit the crontab:

```bash
crontab -e
```

Add entries like the following, replacing the project path if necessary:

```cron
15 8 * * * cd /path/to/forecast_rastered && ./run_forecast.sh 00 >> cron.log 2>&1
15 20 * * * cd /path/to/forecast_rastered && ./run_forecast.sh 12 >> cron.log 2>&1
15 13 * * * cd /path/to/folder/above/forecast_rastered/run_dwd_12Z.sh >> /path/to/forecast_rastered/logs/dwd_13Z.log 2>&1
```
The third entry executes the dwd update at midday to provide the observed data for building the tampertaure mean for the current day out of observed and forecast data for the evening 12Z cycle. Times are GMT.
Save and exit the editor. Check the installed schedule with:

```bash
crontab -l
```

### Cron notes

- The times above are interpreted in the timezone used by the machine running `cron`, not necessarily UTC. The `00` and `12` arguments select the model run cycles; they do not set the cron clock.
- Make sure the WSL/Linux environment is running at the scheduled times. On Windows, scheduled WSL tasks may need additional setup so the environment is awake and `cron` is running.
- Cron jobs have a limited environment. Use absolute paths, and make sure `run_forecast.sh` activates the intended Conda environment itself or otherwise uses the correct Python executable. If Conda activation is required, configure it inside the shell script rather than relying on an interactive terminal setup.
- `cron.log` captures output from the wrapper invocation. Detailed per-downloader and DWD-update logs should be written under the run-specific subfolders in `logs/`.
- Avoid scheduling overlapping runs. Check `cron.log` and `logs/` if a run appears to hang or is still running when the next cycle starts.
- If publishing to GitHub is enabled, the machine needs valid Git remote configuration and authentication that works non-interactively. Never place tokens or passwords directly in this README or in the scripts.

## Conda environment

Create the environment from the supplied file:

```bash
conda env create -f environment.yml
conda activate germany-forecast
```

To update an existing environment from the file:

```bash
conda env update -f environment.yml --prune
```

`environment.yml` is a starting dependency specification. Verify it against the imports and system requirements of the current code before using it to reproduce a production run on another machine. GRIB processing uses `cfgrib` and `eccodes`.

## Data, outputs, and Git

The pipeline creates or updates `data/` and `logs/` during normal operation. Some files under `data/` may be static assets essential to the Germany grid; others may be downloaded or generated during processing. Refer to `config.py` to distinguish them before deciding what to track in Git.

Do not commit credentials, temporary files, logs, or large downloaded forecast caches unless there is a deliberate reason to version them. Keep essential static grid assets available at the paths expected by `config.py`.

Before pushing source changes or published outputs, inspect the repository status:

```bash
git status
git diff --stat
```

Check the publisher's behaviour before running it against a repository that already contains a run directory. Existing published runs should not be overwritten unintentionally.
