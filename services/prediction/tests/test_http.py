"""Exercise the real CherryPy server and HTTP clients against local dependencies.

Run: python -m unittest discover -s tests -v (from services/prediction).
No live ThingSpeak/WAQI accounts or MQTT broker are needed.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import httpx
import joblib
import pandas as pd
import numpy as np
from app.training import train_model_from_csv


SERVICE_DIR = Path(__file__).resolve().parents[1]
METRICS = {"temperature", "humidity", "co2", "pm25"}
HISTORY = [
    {"created_at": "2026-09-30T08:55:00Z", "field2": "19", "field3": "39", "field4": "590", "field5": "9"},
    {"created_at": "2026-09-30T09:00:00Z", "field2": "20", "field3": "40", "field4": "600", "field5": "10"},
    {"created_at": "2026-09-30T09:05:00Z", "field2": "21", "field3": "41", "field4": "610", "field5": "11"},
    {"created_at": "2026-09-30T09:10:00Z", "field2": "22", "field3": "42", "field4": "620", "field5": "12"},
]


class UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, payload):
        content = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Timeout fixtures intentionally close the connection early.

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.registration = payload
        self.reply(503 if self.server.catalog_failed else 200, {"status": "ok"})

    def do_PUT(self):
        self.server.heartbeat = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.reply(200, {"status": "ok"})

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/v1/history":
            query = parse_qs(url.query)
            self.server.history_query = query
            room = query["roomid"][0]
            if room == "slow":
                time.sleep(1)
            if room == "upstream-error":
                self.reply(503, {"detail": "unavailable"})
            elif room == "bad-history":
                self.reply(200, "unsupported history")
            else:
                self.reply(200, [] if room == "missing" else HISTORY)
        elif url.path == "/feed/@13202/":
            self.server.aqi_calls += 1
            if self.server.aqi_failed:
                self.reply(503, {"detail": "WAQI down"})
            else:
                self.reply(200, {"status": "ok", "data": {"aqi": 50}})
        else:
            self.reply(404, {"detail": "Not Found"})


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RunningService:
    def __init__(self, upstream, model_path, token="", heartbeat=False):
        self.log = tempfile.TemporaryFile(mode="w+")
        self.port = unused_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        upstream_url = f"http://127.0.0.1:{upstream.server_port}"
        env = os.environ.copy()
        # Local fixtures must not inherit the host's outbound proxy configuration.
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
        env.update({
            "PORT": str(self.port),
            "MODEL_PATH": str(model_path),
            "ROOM_CATALOG_BASE_URL": upstream_url,
            "THINGSPEAK_ADAPTER_BASE_URL": upstream_url,
            "OUTDOOR_AQI_BASE_URL": upstream_url,
            "OUTDOOR_AQI_TOKEN": token,
            "OUTDOOR_AQI_CITY": "@13202",
            "REQUEST_TIMEOUT_SECONDS": "0.5",
            "ROOM_CATALOG_HEARTBEAT_ENABLED": str(heartbeat),
            "DEFAULT_HORIZON_MINUTES": "15",
            "DEFAULT_LOOKBACK_POINTS": "12",
        })
        self.environment = env
        self.process = subprocess.Popen(
            [sys.executable, "-m", "app.main"], cwd=SERVICE_DIR, env=env,
            stdout=self.log, stderr=subprocess.STDOUT,
        )
        self.client = httpx.Client(base_url=self.base_url, trust_env=False, timeout=10)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                if self.client.get("/health").status_code == 200:
                    return
            except httpx.RequestError:
                time.sleep(0.05)
        self.log.seek(0)
        output = self.log.read()
        self.close()
        raise RuntimeError(f"CherryPy did not become ready:\n{output}")

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            raise AssertionError("CherryPy did not shut down on SIGTERM")
        finally:
            self.client.close()
            self.log.close()


class HttpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        cls.upstream.registration = None
        cls.upstream.heartbeat = None
        cls.upstream.catalog_failed = False
        cls.upstream.aqi_failed = False
        cls.upstream.aqi_calls = 0
        cls.thread = Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.thread.start()
        cls.server = RunningService(cls.upstream, Path(cls.tempdir.name) / "absent.joblib", heartbeat=True)
        cls.client = cls.server.client

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        cls.upstream.shutdown()
        cls.upstream.server_close()
        cls.thread.join()
        cls.tempdir.cleanup()

    def assert_json(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        self.assertIn("application/json", response.headers["Content-Type"])
        return response.json()

    def test_health_and_startup_registration(self):
        data = self.assert_json(self.client.get("/health"))
        self.assertEqual(data["model_source"], "heuristic-baseline")
        self.assertEqual(data["room_catalog_registration"], "registered")
        self.assertEqual(data["default_horizon_minutes"], 15)
        self.assertEqual(self.upstream.registration, {
            "service_id": "prediction-service", "service_name": "prediction-service",
            "type": "prediction", "endpoint": "http://prediction-service:8003",
            "health_endpoint": "/health",
        })
        self.assertEqual(self.upstream.heartbeat, {"service_id": "prediction-service", "status": "online"})

    def test_debug_prediction_baseline_and_field_mapping(self):
        data = self.assert_json(self.client.post("/predict", json={
            "room_id": "room1", "horizon_minutes": 15, "lookback_points": 12,
            "timestamp": "2026-09-30T09:15:00Z", "outdoor_aqi_override": 50,
        }))
        self.assertEqual(data["model_source"], "heuristic-baseline")
        self.assertEqual(data["history_points_used"], 4)
        self.assertEqual(data["indoor_latest"], {"temperature": 22, "humidity": 42, "co2": 620, "pm25": 12})
        self.assertEqual(data["prediction"], {"temperature": 23.25, "humidity": 43.5, "co2": 650, "pm25": 17})
        self.assertEqual(data["outdoor"]["source"], "override")
        self.assertEqual(data["risk"], "normal")
        datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        self.assertEqual(self.upstream.history_query["roomid"], ["room1"])
        self.assertEqual(self.upstream.history_query["endtime"], ["2026-09-30T09:15:00Z"])
        self.assertEqual(self.upstream.history_query["starttime"], ["2026-09-10T09:15:00Z"])

    def test_decision_and_dashboard_contract(self):
        body = self.assert_json(self.client.get("/prediction/room1?horizon_minutes=30&lookback_points=3"))
        self.assertEqual((body["code"], body["msg"]), (0, "success"))
        data = body["data"]
        self.assertEqual(data["room_id"], "room1")
        self.assertEqual(set(data["predictions"]), METRICS)
        for metric in METRICS:
            value = data["predictions"][metric]
            self.assertEqual(set(value), {"value", "horizon_minutes", "generated_at"})
            self.assertEqual(value["horizon_minutes"], 30)
            self.assertIsInstance(value["value"], (float, int))
        self.assertEqual(data["predictions"]["co2"]["value"], 640)

    def test_unconfigured_outdoor_aqi(self):
        data = self.assert_json(self.client.get("/outdoor-aqi"))
        self.assertIsNone(data["aqi"])
        self.assertEqual(data["source"], "unconfigured")

    def test_unknown_query_does_not_override_path_room(self):
        body = self.assert_json(self.client.get("/prediction/room1?room_id=room2&unused=value"))
        self.assertEqual(body["data"]["room_id"], "room1")

    def test_body_validation(self):
        for payload in [{}, {"room_id": "room1", "horizon_minutes": 0},
                        {"room_id": "room1", "horizon_minutes": 181},
                        {"room_id": "room1", "lookback_points": 2},
                        {"room_id": "room1", "lookback_points": 289},
                        {"room_id": "room1", "outdoor_aqi_override": -1},
                        {"room_id": "room1", "timestamp": "yesterday"}, [], None]:
            with self.subTest(payload=payload):
                # httpx's json=None emits no body, so explicitly encode JSON null.
                response = self.client.post("/predict", content=json.dumps(payload), headers={"Content-Type": "application/json"})
                data = self.assert_json(response, 422)
                self.assertEqual(data["detail"][0]["loc"][0], "body")

    def test_query_validation(self):
        for query in ["horizon_minutes=0", "horizon_minutes=181", "horizon_minutes=nope",
                      "lookback_points=2", "lookback_points=289", "lookback_points=nope"]:
            with self.subTest(query=query):
                data = self.assert_json(self.client.get(f"/prediction/room1?{query}"), 422)
                self.assertEqual(data["detail"][0]["loc"][0], "query")

    def test_bad_json_and_content_type(self):
        self.assert_json(self.client.post("/predict", content="{broken", headers={"Content-Type": "application/json"}), 400)
        self.assert_json(self.client.post("/predict", content="room_id=room1", headers={"Content-Type": "text/plain"}), 415)

    def test_missing_history(self):
        for response in [self.client.get("/prediction/missing"), self.client.post("/predict", json={"room_id": "missing"})]:
            data = self.assert_json(response, 404)
            self.assertEqual(data["detail"], "No historical data available for room 'missing'")

    def test_methods_and_paths(self):
        for method, path in [("POST", "/health"), ("GET", "/predict"), ("POST", "/outdoor-aqi"), ("POST", "/prediction/room1")]:
            with self.subTest(method=method, path=path):
                self.assert_json(self.client.request(method, path), 405)
        for path in ["/unknown", "/prediction", "/prediction/room1/extra", "/docs"]:
            with self.subTest(path=path):
                self.assert_json(self.client.get(path), 404)

    def test_upstream_failures_are_json_and_do_not_leak_tracebacks(self):
        for room, status in [("upstream-error", 502), ("slow", 504), ("bad-history", 500)]:
            with self.subTest(room=room):
                response = self.client.get(f"/prediction/{room}")
                self.assert_json(response, status)
                self.assertNotIn("Traceback", response.text)
                self.assertNotIn("http://", response.text)

    def test_concurrent_requests(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda i: self.client.get(f"/prediction/room{i}"), range(8)))
        for index, response in enumerate(responses):
            data = self.assert_json(response)
            self.assertEqual(data["data"]["room_id"], f"room{index}")

    def test_configured_waqi_success_override_and_outage(self):
        server = RunningService(self.upstream, Path(self.tempdir.name) / "absent.joblib", token="test-token")
        try:
            data = self.assert_json(server.client.get("/outdoor-aqi"))
            self.assertEqual((data["aqi"], data["source"]), (50, "waqi-turin"))
            prediction = self.assert_json(server.client.get("/prediction/room1"))
            self.assertEqual(prediction["data"]["predictions"]["co2"]["value"], 650)
            self.upstream.aqi_failed = True
            response = server.client.get("/prediction/room1")
            self.assert_json(response, 502)
            self.assertNotIn("test-token", response.text)
            self.assert_json(server.client.get("/outdoor-aqi"), 502)
            before = self.upstream.aqi_calls
            data = self.assert_json(server.client.post("/predict", json={"room_id": "room1", "outdoor_aqi_override": 0}))
            self.assertEqual(data["outdoor"]["source"], "override")
            self.assertEqual(self.upstream.aqi_calls, before)
        finally:
            self.upstream.aqi_failed = False
            server.close()

    def test_catalog_failure_does_not_prevent_forecasts(self):
        self.upstream.catalog_failed = True
        server = None
        try:
            server = RunningService(self.upstream, Path(self.tempdir.name) / "absent.joblib")
            self.assertEqual(self.assert_json(server.client.get("/health"))["room_catalog_registration"], "failed")
            self.assert_json(server.client.get("/prediction/room1"))
        finally:
            self.upstream.catalog_failed = False
            if server:
                server.close()

    def test_train_from_adaptor_cli_and_check_model(self):
        saved = HISTORY[:]
        i = np.arange(100)
        stamps = pd.date_range("2026-09-29", periods=100, freq="5min", tz="UTC")
        HISTORY[:] = [{"created_at": stamp.isoformat(), "field2": 20+float(np.sin(n/8)),
                       "field3": 45+float(np.cos(n/9)), "field4": 600+n,
                       "field5": 10+float(np.sin(n/7))} for n, stamp in enumerate(stamps)]
        path = Path(self.tempdir.name) / "cli-model.joblib"
        env = {**self.server.environment, "MODEL_PATH": str(path)}
        try:
            missing = subprocess.run([sys.executable, "check_model.py"], cwd=SERVICE_DIR,
                                     env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(missing.returncode, 1)
            self.assertEqual(json.loads(missing.stdout)["fallback_reason"], "artifact_missing")
            result = subprocess.run([sys.executable, "train.py", "--room-id", "room1", "--output-path", str(path)],
                                    cwd=SERVICE_DIR, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(path.is_file())
            checked = subprocess.run([sys.executable, "check_model.py"], cwd=SERVICE_DIR,
                                     env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(checked.stdout)["model_source"], "trained-model")
        finally:
            HISTORY[:] = saved

    def test_model_artifact_path(self):
        # Train actual RFs. Synthetic data tests execution only.
        i = np.arange(100)
        csv = Path(self.tempdir.name) / "training-fixture.csv"
        pd.DataFrame({"timestamp": pd.date_range("2026-09-29", periods=100, freq="5min", tz="UTC"),
                      "temperature": 20 + np.sin(i / 8), "humidity": 45 + np.cos(i / 9),
                      "co2": 600 + i, "pm25": 10 + np.sin(i / 7)}).to_csv(csv, index=False)
        path = Path(self.tempdir.name) / "fixture.joblib"
        train_model_from_csv(str(csv), str(path))
        server = RunningService(self.upstream, path)
        try:
            health = self.assert_json(server.client.get("/health"))
            self.assertEqual(health["model_source"], "trained-model")
            self.assertEqual(health["model"]["self_test"], "passed")
            self.assertIn("RandomForestRegressor", health["model"]["model_type"])
            data = self.assert_json(server.client.post("/predict", json={"room_id": "room1"}))
            self.assertEqual(data["model_source"], "trained-model")
            self.assertEqual(set(data["prediction"]), METRICS)
            self.assertTrue(all(np.isfinite(value) for value in data["prediction"].values()))
            health = self.assert_json(server.client.get("/health"))
            self.assertEqual(health["last_inference"]["model_source"], "trained-model")
            decision = self.assert_json(server.client.get("/prediction/room1"))
            self.assertEqual(decision["data"]["model_source"], "trained-model")
            fallback = self.assert_json(server.client.get("/prediction/room1?horizon_minutes=30"))
            self.assertEqual(fallback["data"]["model_source"], "heuristic-baseline")
            self.assertEqual(fallback["data"]["model_diagnostics"]["fallback_reason"], "unsupported_horizon")
            saved = HISTORY[:]
            try:
                HISTORY[:] = saved[-2:]
                fallback = self.assert_json(server.client.post("/predict", json={"room_id": "room1"}))
                self.assertEqual(fallback["model_source"], "heuristic-baseline")
                self.assertEqual(fallback["model_diagnostics"]["fallback_reason"], "insufficient_recent_history")
            finally:
                HISTORY[:] = saved
        finally:
            server.close()



if __name__ == "__main__":
    unittest.main()
