"""
Centralized storage: in-memory indexed maps (cache) + JSON persistence.
Cache-first reads, write-through on every mutation.
"""
import json
import os
import time
from typing import Dict, Optional


class Storage:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        # Indexed maps: id -> DO dict
        self.devices: Dict[str, dict] = {}
        self.rooms: Dict[str, dict] = {}
        self.policies: Dict[str, dict] = {}
        self.conflicts: Dict[str, dict] = {}
        self.services: Dict[str, dict] = {}

    # ── Bootstrap ────────────────────────────────────────────────────────────

    def load_all(self):
        self.devices = self._load("devices.json", "device_id")
        self.rooms = self._load("rooms.json", "room_id")
        self.policies = self._load("policies.json", "policy_id")
        self.conflicts = self._load("conflicts.json", "conflict_id")
        self.services = self._load("services.json", "service_id")

    def _load(self, filename: str, id_field: str) -> Dict[str, dict]:
        path = os.path.join(self.data_dir, filename)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {item[id_field]: item for item in data}
        return data

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self, filename: str, data: Dict[str, dict]):
        os.makedirs(self.data_dir, exist_ok=True)
        path = os.path.join(self.data_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(list(data.values()), f, indent=2, ensure_ascii=False)

    def save_devices(self):   self._save("devices.json",   self.devices)
    def save_rooms(self):     self._save("rooms.json",     self.rooms)
    def save_policies(self):  self._save("policies.json",  self.policies)
    def save_conflicts(self): self._save("conflicts.json", self.conflicts)
    def save_services(self):  self._save("services.json",  self.services)

    # ── Device helpers ────────────────────────────────────────────────────────

    def upsert_device(self, device_id: str, data: dict):
        data["modified"] = int(time.time())
        self.devices[device_id] = data
        self.save_devices()

    def delete_device(self, device_id: str) -> bool:
        if device_id not in self.devices:
            return False
        del self.devices[device_id]
        self.save_devices()
        return True

    def heartbeat_device(self, device_id: str, update: dict) -> bool:
        dev = self.devices.get(device_id)
        if dev is None:
            return False
        dev["status"] = update.get("status", "online")
        dev["last_seen"] = int(time.time())
        dev["modified"] = dev["last_seen"]
        if dev["category"] == "sensor" and "value" in update:
            dev["last_value"] = update["value"]
        if dev["category"] == "actuator" and "state" in update:
            dev["actual_state"] = update["state"]
        self.save_devices()
        return True

    # ── Auto-offline sweep ────────────────────────────────────────────────────

    def sweep_offline(self, timeout: int):
        now = int(time.time())
        changed = False
        for dev in self.devices.values():
            if dev.get("status") == "online" and now - dev.get("last_seen", 0) > timeout:
                dev["status"] = "offline"
                changed = True
        if changed:
            self.save_devices()

    def sweep_services_offline(self, timeout: int):
        now = int(time.time())
        changed = False
        for svc in self.services.values():
            if svc.get("status") == "online" and now - svc.get("last_seen", 0) > timeout:
                svc["status"] = "offline"
                changed = True
        if changed:
            self.save_services()


# ── Module-level singleton ────────────────────────────────────────────────────

_instance: Optional[Storage] = None


def init(data_dir: str) -> Storage:
    global _instance
    _instance = Storage(data_dir)
    _instance.load_all()
    return _instance


def get() -> Storage:
    return _instance
