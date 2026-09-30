"""One causal feature contract shared by training and live inference."""
import numpy as np
import pandas as pd

TARGETS = ("temperature", "humidity", "co2", "pm25")
INTERVAL_MINUTES = 5
ROLLING_WINDOW = 3
ARTIFACT_VERSION = 1
FEATURE_COLUMNS = [
    name
    for metric in TARGETS
    for name in (metric, f"{metric}_lag_1", f"{metric}_lag_2", f"{metric}_lag_3",
                 f"{metric}_roll_mean", f"{metric}_roll_std", f"{metric}_trend")
] + ["outdoor_aqi", "horizon_minutes", "hour", "weekday"]


def regularize_history(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
    for metric in TARGETS:
        data[metric] = pd.to_numeric(data[metric], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=["timestamp"])
    data.loc[~data.humidity.between(0, 100), "humidity"] = np.nan
    for metric in ("co2", "pm25"):
        data.loc[data[metric] < 0, metric] = np.nan
    # Never blend different rooms into one time series.
    if "room_id" in data and data.room_id.dropna().nunique() > 1:
        raise ValueError("Provide a dataset for one room; mixed-room training is unsupported")
    return data.groupby("timestamp")[list(TARGETS)].mean().sort_index().resample("5min").mean()


def make_feature_frame(regular: pd.DataFrame, horizon_minutes: int, outdoor_aqi=0.0) -> pd.DataFrame:
    # Forward-fill at most 15 minutes. Never interpolate using future samples.
    data = regular.ffill(limit=3)
    frame = pd.DataFrame(index=data.index)
    for metric in TARGETS:
        frame[metric] = data[metric]
        for lag in (1, 2, 3):
            frame[f"{metric}_lag_{lag}"] = data[metric].shift(lag)
        rolling = data[metric].rolling(ROLLING_WINDOW)
        frame[f"{metric}_roll_mean"] = rolling.mean()
        frame[f"{metric}_roll_std"] = rolling.std(ddof=0)
        frame[f"{metric}_trend"] = data[metric].diff()
    frame["outdoor_aqi"] = float(outdoor_aqi or 0.0)
    frame["horizon_minutes"] = float(horizon_minutes)
    frame["hour"] = frame.index.hour.astype(float)
    frame["weekday"] = frame.index.weekday.astype(float)
    return frame[FEATURE_COLUMNS]
