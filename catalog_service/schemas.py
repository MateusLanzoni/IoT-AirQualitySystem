from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
import re
from pydantic import BaseModel, field_validator


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

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
class ScheduleModel(BaseModel):
    start: str = "08:00"
    end: str = "23:00"
    
    @field_validator("start", "end")
    @classmethod
    def _check_time(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("must be 24-hour time in HH:MM format, e.g. 08:00")
        return v

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
Operator = Literal["<", ">", "=", "<=", ">="]
                   
class PolicyCreateDTO(BaseModel):
    policy_id: str
    room_id: str
    metric: str
    operator: Operator               # > | < | >= | <= | =
    value: float
    target_device: str
    target_state: str
    priority: int = 1

class PolicyUpdateDTO(BaseModel):
    room_id: Optional[str] = None
    metric: Optional[str] = None
    operator: Optional[Operator] = None
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
    room_id: Optional[str] = None
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
