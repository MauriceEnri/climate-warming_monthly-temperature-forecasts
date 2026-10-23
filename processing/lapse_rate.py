import pandas as pd
from config import LAPSE_RATE_FILE

def get_lapse_rate(monthly_slopes, valid_time):
    """
    Return the lapse rate for a given forecast valid time.
    """

    key = (valid_time.year, valid_time.month)

    if key not in monthly_slopes:
        raise KeyError(
            f"No lapse rate available for {key}."
        )

    return monthly_slopes[key]

def load_monthly_lapse_rates():
    """
    Load the monthly lapse rates computed from DWD station observations.

    Returns
    -------
    dict
        Dictionary of the form
            {
                (2026, 1): -0.00583,
                (2026, 2): -0.00547,
                ...
            }
        where the values are lapse rates in °C/m.
    """
    df = pd.read_csv(
        LAPSE_RATE_FILE,
        sep="\t"
    )
    required = {
        "year",
        "month",
        "lapse_rate_per_m"
    }
    if not required.issubset(df.columns):
        raise ValueError(
            f"{LAPSE_RATE_FILE} must contain the columns "
            "'year', 'month' and 'lapse_rate_per_m'."
        )
    monthly_slopes = {}
    for _, row in df.iterrows():

        monthly_slopes[
            (int(row["year"]), int(row["month"]))
        ] = float(row["lapse_rate_per_m"])

    return monthly_slopes