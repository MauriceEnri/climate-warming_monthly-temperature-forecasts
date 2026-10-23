from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass
class Forecast:

    model: str

    init_time: pd.Timestamp

    valid_time: pd.Timestamp

    lead_hours: int

    temperature: np.ndarray

    latitude: np.ndarray

    longitude: np.ndarray

    elevation: np.ndarray