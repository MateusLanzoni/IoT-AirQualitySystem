"""
In-memory state store for device states and room config cache.
Thread-safe (used from MQTT callback thread + async processor).
"""
import threading
import time
from typing import Dict, Optional

from load_config import load_config

config = load_config()
class StateStore:
    def __init__(self):
        self._lock = threading.Lock()

        # device_store[room_id][device_id] = {"state": str, "last_action_time": float}
        self._device_store: Dict[str, Dict[str, dict]] = {}

        # metrics_store[room_id] = {"metrics": dict, "timestamp": int, "meta": dict}
        self._metrics_store: Dict[str, dict] = {}

        # config_cache[room_id] = {"config": dict, "last_fetch": float}
        self._config_cache: Dict[str, dict] = {}

    # ── Device state ──────────────────────────────────────────────────────────

    def get_state(self, room_id: str, device_id: str) -> str:
        with self._lock:
            return self._device_store.get(room_id, {}).get(device_id, {}).get("state", "OFF")

    def set_state(self, room_id: str, device_id: str, state: str):
        with self._lock:
            self._device_store.setdefault(room_id, {})
            entry = self._device_store[room_id].setdefault(device_id, {})
            entry["state"] = state
            entry["last_action_time"] = time.time()

    def get_last_action_time(self, room_id: str, device_id: str) -> float:
        with self._lock:
            return self._device_store.get(room_id, {}).get(device_id, {}).get("last_action_time", 0.0)

    def get_all_states(self) -> dict:
        with self._lock:
            return {r: dict(devs) for r, devs in self._device_store.items()}

    # ── Sensor metrics ────────────────────────────────────────────────────────

    def set_metrics(self, room_id: str, metrics: dict, timestamp: int = 0, meta: dict = None):
        with self._lock:
            self._metrics_store[room_id] = {
                "metrics": metrics,
                "timestamp": timestamp,
                "meta": meta or {},
            }

    def get_metrics(self, room_id: str) -> Optional[dict]:
        with self._lock:
            entry = self._metrics_store.get(room_id)
            return dict(entry) if entry else None

    # ── Config cache ──────────────────────────────────────────────────────────
  
    def get_config(self, room_id: str) -> Optional[dict]:
        ttl = config.get("cache", {}).get("room_config_ttl", 3600)
        with self._lock:
            entry = self._config_cache.get(room_id)
            if entry and time.time() - entry["last_fetch"] < ttl:
                return entry["config"]
        return None

    def set_config(self, room_id: str, config: dict):
        with self._lock:
            self._config_cache[room_id] = {"config": config, "last_fetch": time.time()}

 # ── Rooms cache ──────────────────────────────────────────────────────────
    def get_rooms(self) -> Optional[dict]:
        ttl = config.get("cache", {}).get("rooms_ttl", 3600)
        with self._lock:
            entry = self._config_cache.get("rooms")
            if not entry:
                return None

            if time.time() - entry["last_fetch"] >= ttl:
                return None

            return entry["config"]


    def set_rooms(self, config: dict):
        with self._lock:
            self._config_cache["rooms"] = {
                "config": config,
                "last_fetch": time.time()
            }


# Module singleton
_store = StateStore()


def get() -> StateStore:
    return _store
