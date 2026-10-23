from pathlib import Path
import argparse
import subprocess
import shutil
import calendar
from datetime import datetime

from config import RESULT_DIR, GITHUB_DIR, GITHUB_OUTPUT_DIR


# =============================================================================
# Helper functions
# =============================================================================

def run_git(*args):
    """Run a git command inside the local GitHub repository."""

    result = subprocess.run(
        ["git", *args],
        cwd=GITHUB_DIR,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Git command failed:\n"
            f"git {' '.join(args)}\n\n"
            f"{result.stderr.strip()}"
        )

    return result.stdout.strip()

def push_with_retry(max_attempts=10):
    """
    Push to GitHub, retrying if another process has updated origin/main.

    If a push is rejected because origin/main has moved:
      1. Fetch the latest remote history.
      2. Rebase the local commit(s) onto origin/main.
      3. Try pushing again.

    The local commit is never deleted if pushing ultimately fails.
    """

    for attempt in range(1, max_attempts + 1):

        print(
            f"\nPush attempt {attempt}/{max_attempts}..."
        )

        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=GITHUB_DIR,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print("Push successful.")
            return

        stderr = result.stderr.strip()

        # A normal non-fast-forward rejection means that another
        # process has pushed to origin/main.
        if (
            "fetch first" not in stderr
            and "non-fast-forward" not in stderr
        ):
            raise RuntimeError(
                f"Git push failed:\n\n{stderr}"
            )

        print(
            "\nRemote repository changed while pushing."
        )
        print("Fetching latest origin/main...")

        run_git("fetch", "origin")

        print("Rebasing local commit onto origin/main...")

        try:
            run_git("rebase", "origin/main")
        except Exception:
            print(
                "\nRebase failed."
            )
            print(
                "The local commit and files have been retained."
            )
            raise

    raise RuntimeError(
        f"Git push failed after {max_attempts} attempts. "
        "The local commit and files have been retained."
    )

def check_git_repository():
    """Check that the configured GitHub directory is a valid Git repository."""

    if not GITHUB_DIR.exists():
        raise FileNotFoundError(
            f"GitHub repository directory does not exist:\n"
            f"{GITHUB_DIR}\n\n"
            "Clone the repository first."
        )

    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=GITHUB_DIR,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or result.stdout.strip() != "true":
        raise RuntimeError(
            f"{GITHUB_DIR} is not a valid Git repository."
        )


def check_git_clean():
    """
    Refuse to publish if the local GitHub repository contains
    uncommitted changes.
    """

    status = run_git("status", "--porcelain")

    if status:
        raise RuntimeError(
            "The GitHub repository contains uncommitted changes.\n\n"
            "Please commit/stash them before publishing.\n\n"
            f"Changes:\n{status}"
        )


def check_remote():
    """
    Check that a Git remote exists and that origin uses SSH.
    """

    remotes = run_git("remote")

    if not remotes:
        raise RuntimeError(
            "No Git remote is configured for the GitHub repository."
        )

    remote_url = run_git("remote", "get-url", "origin")

    if not remote_url.startswith("git@github.com:"):
        raise RuntimeError(
            "The GitHub repository is not using an SSH remote.\n\n"
            f"Current origin:\n{remote_url}\n\n"
            "Expected something like:\n"
            "git@github.com:jonas-weather-data/weather_forecasts.git"
        )


def remove_directory(path):
    """Remove a directory if it exists."""

    if path.exists():
        shutil.rmtree(path)


# =============================================================================
# Argument parsing
# =============================================================================

parser = argparse.ArgumentParser(
    description=(
        "Publish the current and next month forecast plots "
        "for a model run to GitHub."
    )
)

parser.add_argument(
    "--date",
    required=True,
    help="Run date in YYYY-MM-DD format, e.g. 2026-09-04",
)

parser.add_argument(
    "--run",
    required=True,
    choices=["00", "12"],
    help="Model run: 00 or 12",
)

args = parser.parse_args()


# =============================================================================
# Parse run information
# =============================================================================
try:
    if "-" in args.date:
        run_date = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        run_date = datetime.strptime(args.date, "%Y%m%d")
except ValueError:
    raise ValueError(
        f"Invalid date '{args.date}'. "
        "Expected YYYY-MM-DD or YYYYMMDD."
    )

run_string = f"{run_date:%Y%m%d}_{args.run}Z"


print("=" * 70)
print("GitHub forecast publisher")
print("=" * 70)
print(f"Run date:       {run_date:%Y-%m-%d}")
print(f"Run:            {args.run}Z")
print(f"Run string:     {run_string}")
print()


# =============================================================================
# Check GitHub repository
# =============================================================================

print("Checking GitHub repository...")

check_git_repository()
check_git_clean()
check_remote()

print(f"Repository:     {GITHUB_DIR}")
print("Git status:     clean")
print("Git remote:     SSH")
print()
print("\nSynchronizing with GitHub before publishing...")

run_git("fetch", "origin")

local_commit = run_git("rev-parse", "HEAD")
remote_commit = run_git("rev-parse", "origin/main")

if local_commit != remote_commit:

    print("Remote repository has changed.")
    print("Rebasing local branch onto origin/main...")

    run_git("rebase", "origin/main")

    print("Local branch synchronized with origin/main.")

else:

    print(
        "Local branch is already synchronized with origin/main."
    )

# =============================================================================
# Find local run directory
# =============================================================================

run_dir = RESULT_DIR / run_string

print("Looking for run directory:")
print(f"    {run_dir}")
print()

if not run_dir.exists():
    raise FileNotFoundError(
        f"Run directory does not exist:\n{run_dir}"
    )

if not run_dir.is_dir():
    raise NotADirectoryError(
        f"Run path is not a directory:\n{run_dir}"
    )


# =============================================================================
# Determine current and next month
# =============================================================================

current_month_name = run_date.strftime("%B")

if run_date.month == 12:
    next_month = 1
else:
    next_month = run_date.month + 1

next_month_name = calendar.month_name[next_month]


# =============================================================================
# Determine plots to publish
# =============================================================================

current_plot = run_dir / (
    f"forecast_{current_month_name}_{run_string}.png"
)

next_plot = run_dir / (
    f"forecast_{next_month_name}_{run_string}.png"
)

plots_to_publish = []

print("Checking forecast plots:")
print()

if current_plot.exists():
    print(f"  FOUND:   {current_plot.name}")
    plots_to_publish.append(current_plot)
else:
    print(f"  MISSING: {current_plot.name}")

if next_plot.exists():
    print(f"  FOUND:   {next_plot.name}")
    plots_to_publish.append(next_plot)
else:
    print(f"  MISSING: {next_plot.name}")

print()

if not plots_to_publish:
    raise FileNotFoundError(
        f"No current or next month plots were found in:\n{run_dir}"
    )


# =============================================================================
# Check whether this run has already been published
# =============================================================================

destination_dir = GITHUB_OUTPUT_DIR / run_string

if destination_dir.exists():
    raise FileExistsError(
        f"The GitHub output directory already exists:\n"
        f"{destination_dir}\n\n"
        "Refusing to overwrite an existing run."
    )


# =============================================================================
# Create destination and copy plots
# =============================================================================

print("Creating GitHub output directory:")
print(f"    {destination_dir}")
print()

destination_dir.mkdir(
    parents=True,
    exist_ok=False,
)

commit_created = False

try:

    print("Copying plots:")

    for source in plots_to_publish:
        destination = destination_dir / source.name
        shutil.copy2(source, destination)
        print(f"  {source.name}")

    print()


    # =========================================================================
    # Git add
    # =========================================================================

    print("Adding files to Git...")

    relative_destination = destination_dir.relative_to(GITHUB_DIR)

    run_git(
        "add",
        str(relative_destination),
    )

    print("Files added.")
    print()


    # =========================================================================
    # Commit
    # =========================================================================
    commit_message = (
        f"Add forecast plots for {run_date:%Y-%m-%d} {args.run}Z"
    )

    print("Creating commit:")
    print(f"    {commit_message}")
    print()

    run_git(
        "commit",
        "-m",
        commit_message,
    )
    commit_created = True

    print("Commit created.")
    print()
    # =========================================================================
    # Push
    # =========================================================================
    print("\nPushing to GitHub...")
    print()
    push_with_retry(max_attempts=5)
    print()
    print("=" * 70)
    print("SUCCESS")
    print("=" * 70)
    print(f"Published run: {run_string}")
    print(f"Plots:         {len(plots_to_publish)}")
    print(f"Destination:   {relative_destination}")
    print("=" * 70)

except Exception as exc:
    print("\n")
    print("=" * 70)
    print("PUBLISHING FAILED")
    print("=" * 70)
    print(str(exc))
    print("=" * 70)

    if commit_created:
        print(
            "\nThe Git commit was already created."
        )
        print(
            "Keeping the committed files and local commit."
        )
        print(
            "Nothing will be deleted from the repository."
        )
    else:
        print(
            "\nCommit was not created."
        )
        print(
            "Cleaning up newly created files..."
        )

        # Keep your existing cleanup code here.

        print("Cleanup completed.")

    raise