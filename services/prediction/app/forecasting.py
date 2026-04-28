from __future__ import annotations

import joblib
import numpy as np
from pathlib import Path

from .schemas import ForecastValues, HistoryPoint, IndoorSnapshot


TARGETS = ("temperature", "humidity", "co2", "pm25")


class BaselineForecaster:
    source = "heuristic-baseline"

    def predict_from_series(
        self,
        history: list[HistoryPoint],
        indoor_latest: IndoorSnapshot,
        outdoor_aqi: float | None,
        horizon_minutes: int,
        timestamp,
    ) -> ForecastValues:
        outdoor_value = outdoor_aqi or 0.0
        horizon_scale = horizon_minutes / 15.0

        def project(metric: str, outdoor_weight: float = 0.0) -> float | None:
            current = getattr(indoor_latest, metric)
            if current is None:
                return None

            recent_values = [getattr(point, metric) for point in history if getattr(point, metric) is not None]
            if len(recent_values) >= 2:
                slope = recent_values[-1] - recent_values[-2]
            elif len(recent_values) == 1:
                slope = current - recent_values[-1]
            else:
                slope = 0.0

            projection = current + (slope * horizon_scale) + (outdoor_value * outdoor_weight)
            return round(max(projection, 0.0), 2)

        return ForecastValues(
            temperature=project("temperature", outdoor_weight=0.005) or 0.0,
            humidity=project("humidity", outdoor_weight=0.01) or 0.0,
            co2=project("co2", outdoor_weight=0.4) or 0.0,
            pm25=project("pm25", outdoor_weight=0.08) or 0.0,
        )


class ModelForecaster:
    source = "trained-model"

    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self.model = joblib.load(self.model_path)

    def predict_from_series(
        self,
        history: list[HistoryPoint],
        indoor_latest: IndoorSnapshot,
        outdoor_aqi: float | None,
        horizon_minutes: int,
        timestamp,
    ) -> ForecastValues:
        features = build_feature_vector(
            history=history,
            indoor_latest=indoor_latest,
            outdoor_aqi=outdoor_aqi,
            horizon_minutes=horizon_minutes,
            timestamp=timestamp,
        )
        raw = self.model.predict([features])[0]

        return ForecastValues(
            temperature=round(float(raw[0]), 2),
            humidity=round(float(raw[1]), 2),
            co2=round(float(raw[2]), 2),
            pm25=round(float(raw[3]), 2),
        )


def load_forecaster(model_path: str):
    path = Path(model_path)
    if path.exists():
        try:
            return ModelForecaster(model_path)
        except Exception:
            return BaselineForecaster()
    return BaselineForecaster()


def build_feature_vector(
    history: list[HistoryPoint],
    indoor_latest: IndoorSnapshot,
    outdoor_aqi: float | None,
    horizon_minutes: int,
    timestamp,
) -> np.ndarray:
    outdoor_value = outdoor_aqi or 0.0

    def metric_values(metric: str) -> list[float]:
        values = [float(getattr(point, metric)) for point in history if getattr(point, metric) is not None]
        values.append(float(getattr(indoor_latest, metric) or 0.0))
        return values[-4:]

    features: list[float] = []
    for metric in TARGETS:
        values = metric_values(metric)
        current = values[-1]
        lag_1 = values[-2] if len(values) > 1 else current
        lag_2 = values[-3] if len(values) > 2 else lag_1
        lag_3 = values[-4] if len(values) > 3 else lag_2
        roll_mean = float(np.mean(values))
        roll_std = float(np.std(values)) if len(values) > 1 else 0.0
        trend = current - lag_1 if len(values) > 1 else 0.0
        features.extend(
            [
                current,
                lag_1,
                lag_2,
                lag_3,
                roll_mean,
                roll_std,
                trend,
            ]
        )

    ts = timestamp
    features.extend(
        [
            float(outdoor_value),
            float(horizon_minutes),
            float(ts.hour),
            float(ts.weekday()),
        ]
    )
    return np.array(features, dtype=float)
