"""
In-memory state store for device states and room config cache.
Thread-safe (used from MQTT callback thread + async processor).
"""
import threading
import time
from typing import Dict, Optional


class StateStore:
    def __init__(self):
        self._lock = threading.Lock()

        # device_store[room_id][device_id] = {"state": str, "last_action_time": float}
        self._device_store: Dict[str, Dict[str, dict]] = {}

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

    # ── Config cache ──────────────────────────────────────────────────────────

    def get_config(self, room_id: str, ttl: int) -> Optional[dict]:
        with self._lock:
            entry = self._config_cache.get(room_id)
            if entry and time.time() - entry["last_fetch"] < ttl:
                return entry["config"]
        return None

    def set_config(self, room_id: str, config: dict):
        with self._lock:
            self._config_cache[room_id] = {"config": config, "last_fetch": time.time()}


# Module singleton
_store = StateStore()


def get() -> StateStore:
    return _store
