from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


# ── Shared response wrapper ──────────────────────────────────────────────────

def ok(data: Any = None, msg: str = "success") -> dict:
    return {"code": 0, "msg": msg, "data": data}

def err(msg: str = "error", code: int = 1) -> dict:
    return {"code": code, "msg": msg, "data": None}


# ── Device ───────────────────────────────────────────────────────────────────

class DeviceDTO(BaseModel):
    """API-facing device representation (DTO)."""
    key: str
    name: str
    device_class: str           # temperature | co2 | AC | FAN | WINDOW …
    category: str               # sensor | actuator
    room_id: str
    unit: str = ""


class HeartbeatSensorDTO(BaseModel):
    key: str
    status: str = "online"
    value: float


class HeartbeatActuatorDTO(BaseModel):
    key: str
    state: str


# ── Room ─────────────────────────────────────────────────────────────────────

class ScheduleModel(BaseModel):
    start: str = "08:00"
    end: str = "23:00"

class RoomCreateDTO(BaseModel):
    room_id: str
    device_ids: List[str] = []
    energy_mode: str = "NORMAL"
    schedule: ScheduleModel = ScheduleModel()

class RoomUpdateDTO(BaseModel):
    device_ids: Optional[List[str]] = None
    energy_mode: Optional[str] = None
    schedule: Optional[ScheduleModel] = None


# ── Policy ───────────────────────────────────────────────────────────────────

class PolicyCreateDTO(BaseModel):
    policy_id: str
    room_id: str
    metric: str
    operator: str               # > | < | >= | <= | ==
    value: float
    target_device: str
    target_state: str
    priority: int = 1

class PolicyUpdateDTO(BaseModel):
    metric: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[float] = None
    target_device: Optional[str] = None
    target_state: Optional[str] = None
    priority: Optional[int] = None


# ── Conflict ─────────────────────────────────────────────────────────────────

class ConflictCreateDTO(BaseModel):
    conflict_id: str
    room_id: str
    rule: str                   # mutually_exclusive
    devices: List[str] = []
    strategy: str               # prefer_higher_priority | prefer_lower_energy | prefer_comfort

class ConflictUpdateDTO(BaseModel):
    rule: Optional[str] = None
    devices: Optional[List[str]] = None
    strategy: Optional[str] = None


# ── Service Registry ─────────────────────────────────────────────────────────

class ServiceRegisterDTO(BaseModel):
    service_id: str
    service_name: str
    type: str
    endpoint: str
    health_endpoint: str = "/health"
