"""
All API routers for Catalog Service.

Sections:
  /devices   - Device lifecycle
  /rooms     - Room configuration
  /policies  - Policy CRUD
  /conflicts - Conflict rules CRUD
  /services  - Service registry
  /room      - Aggregation read model
"""
import time
from typing import Optional

from fastapi import APIRouter, HTTPException

import storage as st
from schemas import (
    DeviceDTO, HeartbeatSensorDTO, HeartbeatActuatorDTO,
    RoomCreateDTO, RoomUpdateDTO,
    PolicyCreateDTO, PolicyUpdateDTO,
    ConflictCreateDTO, ConflictUpdateDTO,
    ServiceRegisterDTO,
    ok, err,
)

router = APIRouter()


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _device_to_dto(dev: dict) -> dict:
    return {
        "key": dev["device_id"],
        "name": dev["device_name"],
        "device_class": dev.get("type", ""),
        "category": dev.get("category", ""),
        "room_id": dev.get("room_id", ""),
        "unit": dev.get("unit", ""),
    }


# ────────────────────────────────────────────────────────────────────────────
# DEVICES
# ────────────────────────────────────────────────────────────────────────────

@router.get("/devices")
def list_devices():
    store = st.get()
    dtos = [_device_to_dto(d) for d in store.devices.values()]
    return ok(dtos)


@router.put("/devices/{device_id}")
def update_device(device_id: str, body: DeviceDTO):
    store = st.get()
    existing = store.devices.get(device_id, {})
    # Merge DTO fields back into DO
    existing.update({
        "device_id": body.key,
        "device_name": body.name,
        "type": body.device_class,
        "category": body.category,
        "room_id": body.room_id,
        "unit": body.unit,
        "created": existing.get("created", int(time.time())),
        "metadata": existing.get("metadata", {}),
    })
    store.upsert_device(device_id, existing)
    return ok(None, "updated")


@router.put("/devices/{device_id}/heartbeat")
def device_heartbeat(device_id: str, body: dict):
    store = st.get()
    dev = store.devices.get(device_id)
    if dev is None:
        return err(f"Device {device_id} not found", code=404)

    update: dict = {}
    if "value" in body:        # sensor heartbeat
        update = {"status": body.get("status", "online"), "value": body["value"]}
    elif "state" in body:      # actuator heartbeat
        update = {"state": body["state"]}
    else:
        return err("Missing value or state field")

    store.heartbeat_device(device_id, update)
    return ok(None, "heartbeat recorded")


@router.delete("/devices/{device_id}")
def delete_device(device_id: str):
    store = st.get()
    if not store.delete_device(device_id):
        return err(f"Device {device_id} not found", code=404)
    return ok(None, "deleted")


# ────────────────────────────────────────────────────────────────────────────
# ROOMS
# ────────────────────────────────────────────────────────────────────────────

@router.get("/rooms")
def list_rooms():
    store = st.get()
    return ok(list(store.rooms.values()))


@router.post("/rooms")
def create_room(body: RoomCreateDTO):
    store = st.get()
    if body.room_id in store.rooms:
        return err(f"Room {body.room_id} already exists", code=409)
    room = body.model_dump()
    room["schedule"] = room["schedule"] if isinstance(room["schedule"], dict) else room["schedule"].model_dump()
    store.rooms[body.room_id] = room
    store.save_rooms()
    return ok(None, "created")


@router.get("/rooms/{room_id}")
def get_room(room_id: str):
    store = st.get()
    room = store.rooms.get(room_id)
    if room is None:
        return err(f"Room {room_id} not found", code=404)
    return ok(room)


@router.put("/rooms/{room_id}")
def update_room(room_id: str, body: RoomUpdateDTO):
    store = st.get()
    room = store.rooms.get(room_id)
    if room is None:
        return err(f"Room {room_id} not found", code=404)
    if body.device_ids is not None:
        room["device_ids"] = body.device_ids
    if body.energy_mode is not None:
        room["energy_mode"] = body.energy_mode
    if body.schedule is not None:
        room["schedule"] = body.schedule.model_dump()
    store.save_rooms()
    return ok(None, "updated")


@router.delete("/rooms/{room_id}")
def delete_room(room_id: str):
    store = st.get()
    if room_id not in store.rooms:
        return err(f"Room {room_id} not found", code=404)
    del store.rooms[room_id]
    store.save_rooms()
    return ok(None, "deleted")


# ────────────────────────────────────────────────────────────────────────────
# POLICIES
# ────────────────────────────────────────────────────────────────────────────

@router.post("/policies")
def create_policy(body: PolicyCreateDTO):
    store = st.get()
    if body.policy_id in store.policies:
        return err(f"Policy {body.policy_id} already exists", code=409)
    store.policies[body.policy_id] = body.model_dump()
    store.save_policies()
    return ok(None, "created")


@router.get("/policies")
def list_policies(room_id: Optional[str] = None):
    store = st.get()
    result = list(store.policies.values())
    if room_id:
        result = [p for p in result if p.get("room_id") == room_id]
    return ok(result)


@router.put("/policies/{policy_id}")
def update_policy(policy_id: str, body: PolicyUpdateDTO):
    store = st.get()
    policy = store.policies.get(policy_id)
    if policy is None:
        return err(f"Policy {policy_id} not found", code=404)
    for field, val in body.model_dump(exclude_none=True).items():
        policy[field] = val
    store.save_policies()
    return ok(None, "updated")


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: str):
    store = st.get()
    if policy_id not in store.policies:
        return err(f"Policy {policy_id} not found", code=404)
    del store.policies[policy_id]
    store.save_policies()
    return ok(None, "deleted")


# ────────────────────────────────────────────────────────────────────────────
# CONFLICTS
# ────────────────────────────────────────────────────────────────────────────

@router.post("/conflicts")
def create_conflict(body: ConflictCreateDTO):
    store = st.get()
    if body.conflict_id in store.conflicts:
        return err(f"Conflict rule {body.conflict_id} already exists", code=409)
    store.conflicts[body.conflict_id] = body.model_dump()
    store.save_conflicts()
    return ok(None, "created")


@router.get("/conflicts")
def list_conflicts(room_id: Optional[str] = None):
    store = st.get()
    result = list(store.conflicts.values())
    if room_id:
        result = [c for c in result if c.get("room_id") == room_id]
    return ok(result)


@router.put("/conflicts/{conflict_id}")
def update_conflict(conflict_id: str, body: ConflictUpdateDTO):
    store = st.get()
    conflict = store.conflicts.get(conflict_id)
    if conflict is None:
        return err(f"Conflict {conflict_id} not found", code=404)
    for field, val in body.model_dump(exclude_none=True).items():
        conflict[field] = val
    store.save_conflicts()
    return ok(None, "updated")


@router.delete("/conflicts/{conflict_id}")
def delete_conflict(conflict_id: str):
    store = st.get()
    if conflict_id not in store.conflicts:
        return err(f"Conflict {conflict_id} not found", code=404)
    del store.conflicts[conflict_id]
    store.save_conflicts()
    return ok(None, "deleted")


# ────────────────────────────────────────────────────────────────────────────
# SERVICE REGISTRY
# ────────────────────────────────────────────────────────────────────────────

@router.get("/services")
def list_services():
    store = st.get()
    return ok(list(store.services.values()))


@router.post("/services/register")
def register_service(body: ServiceRegisterDTO):
    store = st.get()
    svc = body.model_dump()
    svc["status"] = "unknown"
    svc["last_seen"] = 0
    store.services[body.service_id] = svc
    store.save_services()
    return ok(None, "registered")


@router.delete("/services/{service_id}")
def delete_service(service_id: str):
    store = st.get()
    if service_id not in store.services:
        return err(f"Service {service_id} not found", code=404)
    del store.services[service_id]
    store.save_services()
    return ok(None, "deleted")


# ────────────────────────────────────────────────────────────────────────────
# AGGREGATION  GET /room/{room_id}
# ────────────────────────────────────────────────────────────────────────────

@router.get("/room/{room_id}")
def get_room_aggregate(room_id: str):
    store = st.get()
    room = store.rooms.get(room_id)
    if room is None:
        return err(f"Room {room_id} not found", code=404)

    # Resolve devices
    sensors, actuators = [], []
    for dev_id in room.get("device_ids", []):
        dev = store.devices.get(dev_id)
        if dev is None:
            continue
        dto = _device_to_dto(dev)
        if dev.get("category") == "sensor":
            sensors.append(dto)
        else:
            actuators.append(dto)

    # Load room-scoped policies and conflicts
    policies = [p for p in store.policies.values() if p.get("room_id") == room_id]
    conflicts = [c for c in store.conflicts.values() if c.get("room_id") == room_id]

    return ok({
        "room_id": room_id,
        "sensors": sensors,
        "actuators": actuators,
        "policies": policies,
        "conflicts": conflicts,
        "energy_mode": room.get("energy_mode", "NORMAL"),
        "schedule": room.get("schedule", {}),
    })
