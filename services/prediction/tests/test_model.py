from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor

from app.clients import normalize_history_response
from app.features import FEATURE_COLUMNS, TARGETS, make_feature_frame, regularize_history
from app.forecasting import ModelInferenceUnavailable, build_feature_vector, load_forecaster
from app.schemas import HistoryPoint, IndoorSnapshot, OutdoorSnapshot, PredictionRequest
from app.service import PredictionService
from app.training import load_dataset, prepare_training_frame, split_features_targets, train_model_from_csv


class FeatureContractTests(unittest.TestCase):
    def test_thingspeak_mapping(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "data.csv"
            pd.DataFrame([{"created_at": "2026-09-30T09:00:00Z", "field2": 22,
                           "field3": 45, "field4": 700, "field5": 12}]).to_csv(path, index=False)
            data = load_dataset(str(path))
            self.assertEqual(data.iloc[0].co2, 700)
            self.assertEqual(data.iloc[0].pm25, 12)

    def test_feature_order_lags_rolling_and_training_parity(self):
        timestamps = pd.date_range("2026-09-30T09:00:00Z", periods=8, freq="5min")
        rows = [{"timestamp": stamp, "temperature": 20+i, "humidity": 40+i,
                 "co2": 600+10*i, "pm25": 10+i} for i, stamp in enumerate(timestamps)]
        history = [HistoryPoint(**row) for row in rows[:4]]
        latest = IndoorSnapshot(**{metric: rows[3][metric] for metric in TARGETS})
        vector = build_feature_vector(history, latest, 0, 15, timestamps[3])
        expected = []
        for start, step in [(20, 1), (40, 1), (600, 10), (10, 1)]:
            expected += [start+3*step, start+2*step, start+step, start,
                         start+2*step, np.sqrt(2/3)*step, step]
        expected += [0, 15, 9, 2]
        np.testing.assert_allclose(vector, expected)
        frame = prepare_training_frame(pd.DataFrame(rows))
        x, _ = split_features_targets(frame)
        self.assertEqual(list(x.columns), FEATURE_COLUMNS)
        np.testing.assert_allclose(x.loc[timestamps[3]], vector)
        duplicate = build_feature_vector(history + [history[-1]], latest, 0, 15, timestamps[3])
        np.testing.assert_allclose(duplicate, vector)

    def test_preprocessing_does_not_fill_from_future(self):
        df = pd.DataFrame({"timestamp": pd.date_range("2026-09-30", periods=5, freq="5min", tz="UTC"),
                           "temperature": [None, None, 22, 23, 24], "humidity": [40]*5,
                           "co2": [600]*5, "pm25": [10]*5})
        features = make_feature_frame(regularize_history(df), 15)
        self.assertTrue(pd.isna(features.iloc[0].temperature))
        self.assertTrue(pd.isna(features.iloc[1].temperature))

    def test_sparse_history_is_preserved_and_forward_filled(self):
        response = normalize_history_response("room1", [
            {"created_at": "2026-09-30T09:00:00Z", "field2": 22},
            {"created_at": "2026-09-30T09:01:00Z", "field3": 45},
            {"created_at": "2026-09-30T09:02:00Z", "field4": 700},
            {"created_at": "2026-09-30T09:03:00Z", "field5": 12},
        ])
        self.assertEqual(len(response.points), 4)
        self.assertEqual(response.latest.model_dump(), {"temperature": 22, "humidity": 45, "co2": 700, "pm25": 12})
        missing = normalize_history_response("room1", [{"created_at": "2026-09-30T09:00:00Z", "field2": 22}])
        self.assertIsNone(missing.latest)

    def test_bad_training_inputs_are_rejected(self):
        data = pd.DataFrame({"timestamp": pd.date_range("2026-09-30", periods=10, freq="5min", tz="UTC"),
                             **{metric: [20]*10 for metric in TARGETS}})
        for horizon in [1, 16, 181]:
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                prepare_training_frame(data, horizon_minutes=horizon)
        data["room_id"] = ["a", "b"] * 5
        with self.assertRaisesRegex(ValueError, "one room"):
            prepare_training_frame(data)


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = TemporaryDirectory()
        cls.path = Path(cls.folder.name) / "rf.joblib"
        csv = Path(cls.folder.name) / "synthetic-fixture.csv"
        i = np.arange(180)
        pd.DataFrame({"timestamp": pd.date_range("2026-09-29", periods=180, freq="5min", tz="UTC"),
                      "temperature": 20+np.sin(i/10), "humidity": 45+np.cos(i/11),
                      "co2": 600+i, "pm25": 10+np.cos(i/9)}).to_csv(csv, index=False)
        cls.stats = train_model_from_csv(str(csv), str(cls.path))
        cls.artifact = joblib.load(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_actual_rf_loads_and_evaluation_is_chronological(self):
        model = load_forecaster(str(self.path))
        self.assertEqual(model.source, "trained-model")
        self.assertEqual(model.diagnostics["self_test"], "passed")
        self.assertEqual([type(e).__name__ for e in model.model.estimators_], ["RandomForestRegressor"]*4)
        evaluation = self.stats["evaluation"]
        self.assertLess(pd.Timestamp(evaluation["train_end"])+timedelta(minutes=15), pd.Timestamp(evaluation["test_start"]))
        self.assertEqual(set(evaluation["metrics"]), set(TARGETS))
        self.assertTrue(self.path.with_suffix(".metrics.json").exists())
        for values in evaluation["metrics"].values():
            self.assertTrue(all(np.isfinite(v) and v >= 0 for v in values.values()))

    def test_missing_and_corrupt_models_explain_fallback(self):
        missing = load_forecaster(str(Path(self.folder.name) / "missing.joblib"))
        self.assertEqual(missing.diagnostics["fallback_reason"], "artifact_missing")
        path = Path(self.folder.name) / "corrupt.joblib"
        path.write_bytes(b"bad artifact")
        self.assertIn("artifact_load_failed", load_forecaster(str(path)).diagnostics["fallback_reason"])

    def test_legacy_model_is_rejected(self):
        path = Path(self.folder.name) / "legacy.joblib"
        joblib.dump(self.artifact["model"], path)
        self.assertIn("Legacy model", load_forecaster(str(path)).diagnostics["fallback_reason"])

    def test_incompatible_features_version_and_wrong_estimator_are_rejected(self):
        for key, value in [("feature_columns", list(reversed(FEATURE_COLUMNS))), ("sklearn_version", "0.0.0")]:
            artifact = {"model": self.artifact["model"], "metadata": {**self.artifact["metadata"], key: value}}
            path = Path(self.folder.name) / f"bad-{key}.joblib"
            joblib.dump(artifact, path)
            self.assertEqual(load_forecaster(str(path)).source, "heuristic-baseline")
        path = Path(self.folder.name) / "not-rf.joblib"
        joblib.dump({"model": DummyRegressor(), "metadata": self.artifact["metadata"]}, path)
        self.assertIn("Random Forest", load_forecaster(str(path)).diagnostics["fallback_reason"])

    def test_model_rejects_untrained_horizon(self):
        model = load_forecaster(str(self.path))
        with self.assertRaisesRegex(ModelInferenceUnavailable, "unsupported_horizon"):
            model.predict_from_series([], None, None, 30, None)

    def test_runtime_inference_failure_reports_baseline_honestly(self):
        history = normalize_history_response("room1", [
            {"timestamp": stamp.isoformat(), "temperature": 20+i, "humidity": 40+i,
             "co2": 600+10*i, "pm25": 10+i}
            for i, stamp in enumerate(pd.date_range("2026-09-30", periods=4, freq="5min", tz="UTC"))
        ])
        clients = Mock()
        clients.thingspeak.fetch_history.return_value = history
        clients.outdoor_aqi.fetch_current.return_value = OutdoorSnapshot(aqi=None, source="unconfigured")
        with patch("app.service.load_forecaster", return_value=load_forecaster(str(self.path))):
            service = PredictionService(clients)
        with patch.object(service.forecaster.model, "predict", side_effect=RuntimeError("fixture failure")):
            response = service.predict(PredictionRequest(room_id="room1"))
        self.assertEqual(response.model_source, "heuristic-baseline")
        self.assertEqual(response.model_diagnostics["fallback_reason"], "model_inference_failed: RuntimeError")
        self.assertEqual(service.last_inference["model_source"], "heuristic-baseline")


if __name__ == "__main__":
    unittest.main()
