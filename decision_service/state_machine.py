"""
Device State Machine.

States:   OFF | TURNING_ON | ON | TURNING_OFF | ERROR
Transitions driven by desired target state + execution feedback.
"""
import logging
import time
from typing import Optional

import state_store as ss

logger = logging.getLogger(__name__)

TIMEOUT = 10  # seconds before TURNING_* → ERROR (overridden by config)


def _make_command(device_id: str, command: str, target_state: str, reason: str) -> dict:
    return {
        "device_id": device_id,
        "command": command,
        "target_state": target_state,
        "reason": reason,
        "timestamp": int(time.time() * 1000),
    }


def transition(room_id: str, device_id: str, target_state: str, reason: str, timeout: int = TIMEOUT) -> Optional[dict]:
    """
    Compute state machine transition. Returns a command dict if a command
    must be published, or None if already in the desired state.
    """
    store = ss.get()
    current = store.get_state(room_id, device_id)

    # Handle timeout for in-progress states
    if current in ("TURNING_ON", "TURNING_OFF"):
        elapsed = time.time() - store.get_last_action_time(room_id, device_id)
        if elapsed > timeout:
            logger.warning(f"{device_id} timed out in {current} → ERROR")
            store.set_state(room_id, device_id, "ERROR")
            current = "ERROR"

    # State machine transitions
    if current == "OFF" and target_state in ("ON", "OPEN"):
        store.set_state(room_id, device_id, "TURNING_ON")
        return _make_command(device_id, "TURN_ON", target_state, reason)

    if current == "ON" and target_state in ("OFF", "CLOSED"):
        store.set_state(room_id, device_id, "TURNING_OFF")
        return _make_command(device_id, "TURN_OFF", target_state, reason)

    if current == "OPEN" and target_state in ("CLOSED", "OFF"):
        store.set_state(room_id, device_id, "TURNING_OFF")
        return _make_command(device_id, "TURN_OFF", target_state, reason)

    if current == "CLOSED" and target_state in ("OPEN", "ON"):
        store.set_state(room_id, device_id, "TURNING_ON")
        return _make_command(device_id, "TURN_ON", target_state, reason)

    if current == "ERROR":
        logger.warning(f"{device_id} in ERROR state — skipping command")
        return None

    # Already in desired state or in-progress — no new command
    return None


def handle_feedback(room_id: str, device_id: str, result: str, reported_state: str):
    """Process execution feedback from device status MQTT messages."""
    store = ss.get()
    current = store.get_state(room_id, device_id)

    if result == "SUCCESS":
        store.set_state(room_id, device_id, reported_state)
        logger.info(f"{device_id} feedback SUCCESS → state={reported_state}")
    elif result == "FAILURE":
        store.set_state(room_id, device_id, "ERROR")
        logger.warning(f"{device_id} feedback FAILURE → ERROR")
