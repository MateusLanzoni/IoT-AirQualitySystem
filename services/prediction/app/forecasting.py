from __future__ import annotations

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.multioutput import MultiOutputRegressor

from .features import ARTIFACT_VERSION, FEATURE_COLUMNS, TARGETS, make_feature_frame, regularize_history
from .schemas import ForecastValues, HistoryPoint, IndoorSnapshot

logger = logging.getLogger(__name__)


class ModelInferenceUnavailable(ValueError):
    pass


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
        artifact = joblib.load(self.model_path)
        if not isinstance(artifact, dict) or "metadata" not in artifact or "model" not in artifact:
            raise ValueError("Legacy model artifact: retrain with the corrected feature contract")
        self.metadata = artifact["metadata"]
        self.model = artifact["model"]
        metadata = self.metadata
        if metadata.get("artifact_version") != ARTIFACT_VERSION or metadata.get("feature_columns") != FEATURE_COLUMNS:
            raise ValueError("Incompatible model feature contract: retrain the model")
        if metadata.get("targets") != list(TARGETS) or metadata.get("interval_minutes") != 5:
            raise ValueError("Incompatible model targets or history interval")
        horizon = metadata.get("horizon_minutes")
        if not isinstance(horizon, int) or horizon < 5 or horizon > 180 or horizon % 5:
            raise ValueError("Invalid trained horizon in model metadata")
        if metadata.get("sklearn_version") != sklearn.__version__:
            raise ValueError("scikit-learn version mismatch: retrain in the prediction runtime")
        if not isinstance(self.model, MultiOutputRegressor) or len(getattr(self.model, "estimators_", [])) != 4:
            raise ValueError("Expected a fitted multi-output Random Forest")
        if not all(isinstance(e, RandomForestRegressor) for e in self.model.estimators_):
            raise ValueError("Artifact does not contain Random Forest estimators")
        if list(getattr(self.model, "feature_names_in_", [])) != FEATURE_COLUMNS:
            raise ValueError("Model input names do not match the feature contract")
        probe = pd.DataFrame([[0.0] * len(FEATURE_COLUMNS)], columns=FEATURE_COLUMNS)
        values = self.model.predict(probe)
        if np.shape(values) != (1, 4) or not np.isfinite(values).all():
            raise ValueError("Model inference self-test failed")
        self.diagnostics = {
            "loaded": True, "artifact_exists": True, "path": str(self.model_path),
            "fallback_reason": None, "self_test": "passed", "model_type": metadata["model_type"],
            "trained_horizon_minutes": horizon, "trained_at": metadata.get("trained_at"),
            "outdoor_aqi_trained": metadata.get("outdoor_aqi_trained", False),
            "evaluation": metadata.get("evaluation"),
        }

    def predict_from_series(self, history, indoor_latest, outdoor_aqi, horizon_minutes, timestamp):
        if horizon_minutes != self.metadata["horizon_minutes"]:
            raise ModelInferenceUnavailable("unsupported_horizon")
        # The CSV has no outdoor history: do not feed unseen AQI values to the RF.
        aqi = outdoor_aqi if self.metadata.get("outdoor_aqi_trained") else 0.0
        features = build_feature_vector(history, indoor_latest, aqi, horizon_minutes, timestamp)
        try:
            values = self.model.predict(pd.DataFrame([features], columns=FEATURE_COLUMNS))[0]
        except Exception as exc:
            logger.exception("Random Forest inference failed")
            raise ModelInferenceUnavailable(f"model_inference_failed: {type(exc).__name__}") from exc
        if len(values) != 4 or not np.isfinite(values).all():
            raise ModelInferenceUnavailable("invalid_model_output")
        return ForecastValues(**{metric: round(float(value), 2) for metric, value in zip(TARGETS, values)})


def load_forecaster(model_path: str):
    path = Path(model_path)
    reason = "artifact_missing"
    if path.is_file():
        try:
            return ModelForecaster(model_path)
        except Exception as exc:
            reason = f"artifact_load_failed: {type(exc).__name__}: {exc}"
    logger.warning("Using heuristic-baseline: %s (model path: %s)", reason, path)
    forecaster = BaselineForecaster()
    forecaster.diagnostics = {"loaded": False, "artifact_exists": path.is_file(), "path": str(path),
                              "fallback_reason": reason, "self_test": "not-run"}
    return forecaster


def build_feature_vector(history, indoor_latest, outdoor_aqi, horizon_minutes, timestamp) -> np.ndarray:
    if not history:
        raise ModelInferenceUnavailable("insufficient_recent_history")
    df = pd.DataFrame([{"timestamp": p.timestamp, **{metric: getattr(p, metric) for metric in TARGETS}} for p in history])
    regular = regularize_history(df)
    frame = make_feature_frame(regular, horizon_minutes, outdoor_aqi)
    # Use the latest history bin, not request wall-clock time or a duplicate snapshot.
    if frame.empty or frame.iloc[-1].isna().any():
        raise ModelInferenceUnavailable("insufficient_recent_history")
    return frame.iloc[-1].to_numpy(dtype=float)
