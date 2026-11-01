#!/bin/bash
set -e

PROJECT_DIR="/mnt/c/Users/user/Documents/projects_stuff/climate_change/forecast_rastered"
PARENT_DIR="/mnt/c/Users/user/Documents/projects_stuff/climate_change"

RUN="$1"

if [[ "$RUN" != "00" && "$RUN" != "12" ]]; then
    echo "ERROR: Run must be 00 or 12."
    echo "Usage: ./run_forecast.sh 00"
    echo "       ./run_forecast.sh 12"
    exit 1
fi

DATE=$(date +%Y%m%d)  #-d "yesterday"

LOG_DIR="$PROJECT_DIR/logs/${DATE}_${RUN}Z"
mkdir -p "$LOG_DIR"

echo "======================================================================"
echo "Starting forecast run"
echo "Date: ${DATE}"
echo "Run:  ${RUN}Z"
echo "======================================================================"

source /home/bigetna/miniconda3/etc/profile.d/conda.sh
conda activate climate

echo "Conda environment: $CONDA_DEFAULT_ENV"
echo "Python: $(which python3)"
echo

# ------------------------------------------------------------------
# DWD downloader with inactivity watchdog
# ------------------------------------------------------------------

DWD_HEARTBEAT="$PROJECT_DIR/data/dwd_progress.txt"
DWD_TIMEOUT=600        # 10 minutes
DWD_MAX_ATTEMPTS=20

run_dwd_with_watchdog() {

    local run="$1"
    local attempt=1

    while [[ "$attempt" -le "$DWD_MAX_ATTEMPTS" ]]; do

        echo
        echo "============================================================"
        echo "DWD attempt $attempt/$DWD_MAX_ATTEMPTS"
        echo "============================================================"

        # Remove heartbeat from previous attempt
        rm -f "$DWD_HEARTBEAT"

        # Start DWD and save its output to a dedicated log
        (
            cd "$PARENT_DIR"
            export DWD_HEARTBEAT
            python3 -u "update_dwd_rastered_means.py" --run "$run"
        ) > "$LOG_DIR/dwd_attempt_${attempt}.log" 2>&1 &
        local dwd_pid=$!

        echo "DWD PID: $dwd_pid"

        # Wait until the Python script creates its heartbeat
        while [[ ! -f "$DWD_HEARTBEAT" ]]; do

            if ! kill -0 "$dwd_pid" 2>/dev/null; then
                echo "DWD process exited before creating heartbeat."
                wait "$dwd_pid" || true
                break
            fi

            sleep 10
        done

        # Monitor DWD
        while kill -0 "$dwd_pid" 2>/dev/null; do

            if [[ -f "$DWD_HEARTBEAT" ]]; then

                last_update=$(stat -c %Y "$DWD_HEARTBEAT")
                now=$(date +%s)

                inactive=$((now - last_update))

                echo "DWD heartbeat: ${inactive}s since last progress"

                if [[ "$inactive" -ge "$DWD_TIMEOUT" ]]; then

                    echo
                    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
                    echo "DWD appears to be stuck."
                    echo "No progress for $((DWD_TIMEOUT / 60)) minutes."
                    echo "Killing DWD process $dwd_pid and restarting."
                    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
                    echo

                    kill "$dwd_pid" 2>/dev/null || true

                    # Give it a moment to terminate
                    sleep 5

                    # Force kill if necessary
                    if kill -0 "$dwd_pid" 2>/dev/null; then
                        kill -9 "$dwd_pid" 2>/dev/null || true
                    fi

                    wait "$dwd_pid" || true

                    break
                fi

            else
                echo "Waiting for DWD heartbeat..."
            fi

            sleep 60
        done

        # Check whether DWD actually finished
        if ! kill -0 "$dwd_pid" 2>/dev/null; then

            wait "$dwd_pid"
            dwd_status=$?

            if [[ "$dwd_status" -eq 0 ]]; then
                echo
                echo "DWD completed successfully."
                return 0
            fi

            echo
            echo "DWD exited with status $dwd_status."
        fi

        attempt=$((attempt + 1))

        if [[ "$attempt" -le "$DWD_MAX_ATTEMPTS" ]]; then
            echo "Restarting DWD in 30 seconds..."
            sleep 30
        fi
    done

    echo
    echo "============================================================"
    echo "DWD FAILED after $DWD_MAX_ATTEMPTS attempts."
    echo "Processing will NOT continue."
    echo "============================================================"

    return 1
}
# ------------------------------------------------------------
# Function: retry a model downloader
# ------------------------------------------------------------
run_model_with_retry() {
    local name="$1"
    shift

    local max_attempts=500
    local attempt

    for ((attempt=1; attempt<=max_attempts; attempt++)); do

        echo "[$name] Attempt $attempt/$max_attempts"

        if "$@"; then
            echo "[$name] Completed successfully."
            return 0
        fi

        echo "[$name] Failed."

        if [[ "$attempt" -lt "$max_attempts" ]]; then
            echo "[$name] Retrying in 30 seconds..."
            sleep 30
        fi
    done

    echo "[$name] FAILED after $max_attempts attempts."
    return 1
}

# ============================================================
# Start independent model downloads/DWD data update in parallel
# ============================================================

PID_DWD=""

if [[ "$RUN" == "00" ]]; then

    echo "Starting DWD daily mean update..."
    run_dwd_with_watchdog "$RUN" \
        > "$LOG_DIR/dwd_watchdog.log" 2>&1 &
    PID_DWD=$!

else

    echo "12Z run: DWD update is handled separately at 13:00 local time."
    echo "12Z run will use the existing DWD daily/monthly/lapse-rate files."

fi

echo "Starting AIFS ensemble download..."
(
    run_model_with_retry \
        "AIFS" \
        bash -c "
            cd '$PROJECT_DIR'
            python3 -m downloaders.download_ecmwf_members \
                --system AIFS \
                --ensemble \
                --date '$DATE' \
                --run '$RUN'
        "
) > "$LOG_DIR/aifs.log" 2>&1 &
PID_AIFS=$!

echo "Starting IFS ensemble download..."
(
    run_model_with_retry \
        "IFS" \
        bash -c "
            cd '$PROJECT_DIR'
            python3 -m downloaders.download_ecmwf_members \
                --system IFS \
                --ensemble \
                --date '$DATE' \
                --run '$RUN'
        "
) > "$LOG_DIR/ifs.log" 2>&1 &
PID_IFS=$!

echo "Starting ICON-EU ensemble download..."
(
    run_model_with_retry \
        "ICON-EU" \
        bash -c "
            cd '$PROJECT_DIR'
            python3 -m downloaders.download_icon_eu_eps \
                --date '$DATE' \
                --run '$RUN'
        "
) > "$LOG_DIR/icon_eu.log" 2>&1 &
PID_ICON=$!

echo "Starting GFS ensemble download..."
(
    run_model_with_retry \
        "GFS" \
        bash -c "
            cd '$PROJECT_DIR'
            python3 -m downloaders.download_gfs \
                --ensemble \
                --max-fhr 384 \
                --date '$DATE' \
                --run '$RUN'
        "
) > "$LOG_DIR/gfs.log" 2>&1 &
PID_GFS=$!

echo
echo "All downloads/data processing started in parallel."
echo

# ============================================================
# Wait for all jobs to finish and collect exit codes
# ============================================================

DWD_STATUS=0
AIFS_STATUS=0
IFS_STATUS=0
ICON_STATUS=0
GFS_STATUS=0

if [[ "$RUN" == "00" ]]; then
    echo "Waiting for DWD update..."
    wait $PID_DWD || DWD_STATUS=$?
else
    echo "12Z run: no DWD update to wait for."
fi

echo "Waiting for AIFS..."
wait $PID_AIFS || AIFS_STATUS=$?

echo "Waiting for IFS..."
wait $PID_IFS || IFS_STATUS=$?

echo "Waiting for ICON-EU..."
wait $PID_ICON || ICON_STATUS=$?

echo "Waiting for GFS..."
wait $PID_GFS || GFS_STATUS=$?

echo
echo "======================================================================"
echo "Download summary"
echo "======================================================================"

if [[ $DWD_STATUS -eq 0 ]]; then
    echo "DWD:      SUCCESS"
else
    echo "DWD:      FAILED (exit code $DWD_STATUS)"
fi

if [[ $AIFS_STATUS -eq 0 ]]; then
    echo "AIFS:     SUCCESS"
else
    echo "AIFS:     FAILED (exit code $AIFS_STATUS)"
fi

if [[ $IFS_STATUS -eq 0 ]]; then
    echo "IFS:      SUCCESS"
else
    echo "IFS:      FAILED (exit code $IFS_STATUS)"
fi

if [[ $ICON_STATUS -eq 0 ]]; then
    echo "ICON-EU:  SUCCESS"
else
    echo "ICON-EU:  FAILED (exit code $ICON_STATUS)"
fi

if [[ $GFS_STATUS -eq 0 ]]; then
    echo "GFS:      SUCCESS"
else
    echo "GFS:      FAILED (exit code $GFS_STATUS)"
fi

echo

# ----------------------------------------------------------------------
# Check DWD raster mean update status
# ----------------------------------------------------------------------

if [[ $DWD_STATUS -ne 0 ]]; then
    echo "======================================================================"
    echo "ERROR: DWD UPDATE FAILED"
    echo "======================================================================"
    echo
    echo "The model downloads have finished, but the DWD data update failed."
    echo "run_processing.py will NOT be started."
    echo
    exit 1
fi

# ----------------------------------------------------------------------
# Check which model downloaders failed
# ----------------------------------------------------------------------

MODEL_FAILURES=0

if [[ $AIFS_STATUS -ne 0 ]]; then MODEL_FAILURES=$((MODEL_FAILURES + 1)); fi
if [[ $IFS_STATUS -ne 0 ]]; then MODEL_FAILURES=$((MODEL_FAILURES + 1)); fi
if [[ $ICON_STATUS -ne 0 ]]; then MODEL_FAILURES=$((MODEL_FAILURES + 1)); fi
if [[ $GFS_STATUS -ne 0 ]]; then MODEL_FAILURES=$((MODEL_FAILURES + 1)); fi

# ----------------------------------------------------------------------
# IMPORTANT:
# Do NOT use downloader exit codes to decide whether processing runs.
#
# A downloader can fail after successfully downloading some members.
# Therefore, check whether usable forecast files where downloaded before crashing.
# ----------------------------------------------------------------------

NORMALIZED_DIR="$PROJECT_DIR/data/normalized"

echo "======================================================================"
echo "Checking downloaded forecast files"
echo "======================================================================"
echo
echo "Searching:"
echo "$NORMALIZED_DIR"
echo

CURRENT_FORECAST_FILES=$(find "$NORMALIZED_DIR" \
    -type f \
    -name "*_${DATE}_${RUN}Z.nc")

AVAILABLE_FORECASTS=$(printf '%s\n' "$CURRENT_FORECAST_FILES" | \
    grep -c '\.nc$' || true)

echo "Found $AVAILABLE_FORECASTS forecast file(s) for ${DATE}_${RUN}Z."

if [[ "$AVAILABLE_FORECASTS" -gt 0 ]]; then
    echo
    echo "Available current-run forecast files:"
    printf '%s\n' "$CURRENT_FORECAST_FILES"
    echo
fi

# ----------------------------------------------------------------------
# If no forecast files exist at all, stop.
# ----------------------------------------------------------------------

if [[ "$AVAILABLE_FORECASTS" -eq 0 ]]; then
    echo "======================================================================"
    echo "ERROR: NO FORECAST FILES AVAILABLE"
    echo "======================================================================"
    echo
    echo "The DWD update succeeded, but no forecast model files were found."
    echo "run_processing.py will NOT be started."
    echo
    exit 1
fi

# ----------------------------------------------------------------------
# Some downloaders may have failed, but usable files exist.
# Continue regardless of downloader exit status.
# ----------------------------------------------------------------------

if [[ $MODEL_FAILURES -gt 0 ]]; then
    echo "======================================================================"
    echo "WARNING: SOME MODEL DOWNLOADERS FAILED"
    echo "======================================================================"
    echo
    echo "One or more downloaders exited with an error."
    echo "However, usable forecast files were found."
    echo
    echo "run_processing.py will continue and process the available members."
    echo
else
    echo "All model downloaders completed successfully."
    echo
fi

# ============================================================
# Process available forecasts and publish
# ============================================================

cd "$PROJECT_DIR"

python3 -m run_processing \
    --date "$DATE" \
    --run "$RUN"

echo
echo "======================================================================"
echo "Forecast run completed successfully."
echo "======================================================================"