from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.multioutput import MultiOutputRegressor

FEATURES = [
    "temperature",
    "humidity",
    "pm25",
    "co2",
]


def load_dataset(csv_path: str) -> pd.DataFrame:
    sample = pd.read_csv(csv_path, nrows=5)
    if {"timestamp", "temperature", "humidity", "pm25", "co2"}.issubset(sample.columns):
        df = pd.read_csv(csv_path, usecols=["timestamp", "temperature", "humidity", "pm25", "co2"])
    else:
        df = pd.read_csv(csv_path, usecols=["created_at", "field2", "field3", "field4", "field5"])
        df = df.rename(
            columns={
                "created_at": "timestamp",
                "field2": "temperature",
                "field3": "humidity",
                "field4": "pm25",
                "field5": "co2",
            }
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for column in FEATURES:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    return df


def prepare_training_frame(df: pd.DataFrame, resample_rule: str = "5min", horizon_minutes: int = 15) -> pd.DataFrame:
    aggregated = (
        df.groupby("timestamp")[FEATURES]
        .mean()
        .sort_index()
        .resample(resample_rule)
        .mean()
        .interpolate(limit_direction="both")
        .dropna()
    )

    lag_steps = [1, 2, 3]
    rolling_window = 3

    frame = aggregated.copy()
    for feature in FEATURES:
        for lag in lag_steps:
            frame[f"{feature}_lag_{lag}"] = frame[feature].shift(lag)
        frame[f"{feature}_roll_mean"] = frame[feature].rolling(rolling_window).mean()
        frame[f"{feature}_roll_std"] = frame[feature].rolling(rolling_window).std().fillna(0.0)
        frame[f"{feature}_trend"] = frame[feature].diff().fillna(0.0)

    frame["hour"] = frame.index.hour
    frame["weekday"] = frame.index.weekday
    frame["outdoor_aqi"] = 0.0
    frame["horizon_minutes"] = float(horizon_minutes)

    horizon_steps = max(int(horizon_minutes / 5), 1)
    for feature in FEATURES:
        frame[f"target_{feature}"] = frame[feature].shift(-horizon_steps)

    frame = frame.dropna()
    return frame


def split_features_targets(frame: pd.DataFrame):
    target_columns = [f"target_{feature}" for feature in FEATURES]
    x = frame.drop(columns=target_columns)
    y = frame[target_columns]
    return x, y


def train_model_from_csv(
    csv_path: str,
    output_path: str,
    horizon_minutes: int = 15,
    max_samples: int = 25000,
) -> dict[str, float]:
    df = load_dataset(csv_path)
    frame = prepare_training_frame(df=df, horizon_minutes=horizon_minutes)
    if max_samples and len(frame) > max_samples:
        frame = frame.tail(max_samples)
    x, y = split_features_targets(frame)

    model = MultiOutputRegressor(
        RandomForestRegressor(
            n_estimators=40,
            max_depth=10,
            random_state=42,
            n_jobs=-1,
        )
    )
    model.fit(x, y)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    import joblib

    joblib.dump(model, output)
    return {
        "rows": float(len(df)),
        "training_samples": float(len(frame)),
        "feature_count": float(x.shape[1]),
        "target_count": float(y.shape[1]),
    }
