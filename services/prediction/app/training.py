from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.multioutput import MultiOutputRegressor

from .features import (ARTIFACT_VERSION, FEATURE_COLUMNS, INTERVAL_MINUTES,
                       TARGETS, make_feature_frame, regularize_history)

FEATURES = list(TARGETS)


def load_dataset(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if not {"timestamp", *TARGETS}.issubset(df.columns):
        required = {"created_at", "field2", "field3", "field4", "field5"}
        if not required.issubset(df.columns):
            raise ValueError("CSV must contain timestamp + four metrics, or ThingSpeak created_at + field2-field5")
        df = df.rename(columns={"created_at": "timestamp", "field2": "temperature",
                                "field3": "humidity", "field4": "co2", "field5": "pm25"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    for column in FEATURES:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["timestamp"])


def prepare_training_frame(df: pd.DataFrame, resample_rule="5min", horizon_minutes=15):
    if resample_rule != "5min":
        raise ValueError("Training and inference require the same 5-minute interval")
    if horizon_minutes < 5 or horizon_minutes > 180 or horizon_minutes % 5:
        raise ValueError("Training horizon must be a multiple of 5 between 5 and 180 minutes")
    regular = regularize_history(df)
    frame = make_feature_frame(regular, horizon_minutes)
    steps = horizon_minutes // INTERVAL_MINUTES
    for metric in TARGETS:
        # Targets must be observed values; do not score on interpolated labels.
        frame[f"target_{metric}"] = regular[metric].shift(-steps)
    return frame.replace([np.inf, -np.inf], np.nan).dropna()


def split_features_targets(frame):
    return frame[FEATURE_COLUMNS], frame[[f"target_{metric}" for metric in TARGETS]]


def new_model():
    return MultiOutputRegressor(RandomForestRegressor(
        n_estimators=40, max_depth=10, random_state=42, n_jobs=-1,
    ))


def train_model_from_csv(csv_path, output_path, horizon_minutes=15, max_samples=25000):
    if max_samples < 0:
        raise ValueError("max_samples must be zero (unlimited) or positive")
    df = load_dataset(csv_path)
    frame = prepare_training_frame(df, horizon_minutes=horizon_minutes)
    if max_samples and len(frame) > max_samples:
        frame = frame.tail(max_samples)
    if len(frame) < 30:
        raise ValueError(f"Need at least 30 complete training samples after preprocessing; found {len(frame)}")
    x, y = split_features_targets(frame)
    split = int(len(frame) * 0.8)
    test_start = frame.index[split]
    # Purge training labels that reach the held-out period.
    mask = frame.index[:split] + pd.Timedelta(minutes=horizon_minutes) < test_start
    train_x = x.iloc[:split].loc[mask]
    train_y = y.loc[train_x.index]
    test_x, test_y = x.iloc[split:], y.iloc[split:]
    if len(train_x) < 10 or len(test_x) < 5:
        raise ValueError("Not enough samples for chronological evaluation at this horizon")
    evaluated_model = new_model()
    evaluated_model.fit(train_x, train_y)
    predicted = evaluated_model.predict(test_x)
    # Persistence is a transparent comparison: the latest value at prediction time.
    persistence = test_x[list(TARGETS)].to_numpy()
    metrics = {}
    for index, metric in enumerate(TARGETS):
        actual = test_y.iloc[:, index]
        metrics[metric] = {
            "mae": float(mean_absolute_error(actual, predicted[:, index])),
            "rmse": float(np.sqrt(mean_squared_error(actual, predicted[:, index]))),
            "persistence_mae": float(mean_absolute_error(actual, persistence[:, index])),
            "persistence_rmse": float(np.sqrt(mean_squared_error(actual, persistence[:, index]))),
        }
    evaluation = {
        "method": "chronological_80_20_with_horizon_purge",
        "training_samples": len(train_x), "test_samples": len(test_x),
        "train_end": train_x.index[-1].isoformat(), "test_start": test_start.isoformat(),
        "metrics": metrics,
        "note": "Metrics are held-out estimates for this dataset; no accuracy percentage is claimed.",
    }
    # The deployable artifact is refitted on all usable data after evaluation.
    model = new_model()
    model.fit(x, y)
    metadata = {
        "artifact_version": ARTIFACT_VERSION, "feature_columns": FEATURE_COLUMNS,
        "targets": list(TARGETS), "interval_minutes": INTERVAL_MINUTES,
        "horizon_minutes": horizon_minutes, "outdoor_aqi_trained": False,
        "model_type": "MultiOutputRegressor[RandomForestRegressor]",
        "sklearn_version": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_start": frame.index[0].isoformat(), "data_end": frame.index[-1].isoformat(),
        "training_samples": len(frame), "evaluation": evaluation,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "metadata": metadata}, output)
    output.with_suffix(".metrics.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return {"rows": len(df), "training_samples": len(frame), "feature_count": len(FEATURE_COLUMNS),
            "target_count": len(TARGETS), "evaluation": evaluation, "output_path": str(output)}
