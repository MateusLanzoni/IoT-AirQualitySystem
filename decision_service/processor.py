"""
Main decision processing pipeline.
Called for each sensor state event received via MQTT.

Pipeline:
  1. Validate timestamp freshness
  2. Filter abnormal metric values
  3. Fetch predictions (REST, optional)
  4. Fetch room config from Catalog (REST, with cache)
  5. Evaluate policies → candidate actions
  6. Apply energy mode adjustments
  7. Resolve conflicts
  8. State machine transitions → commands
  9. Publish control commands (MQTT)
 10. Publish decision log (MQTT)
"""

from ast import Store
import asyncio

import logging
import time
import traceback
from typing import Dict, List, Optional

import httpx
from opentelemetry import metrics

import policy_engine
import energy_mode as em
import conflict_resolver
import state_machine as sm
import state_store as ss

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _filter_abnormal(metrics: Dict[str, float], limits: dict, room_id: str = "", mqtt_pub=None) -> Dict[str, float]:
    """Remove metric values outside configured min/max bounds and alert on violations."""
    clean = {}
    for key, val in metrics.items():
        lim = limits.get(key)
        if lim is None:
            clean[key] = val
            continue
        if lim["min"] <= val <= lim["max"]:
            clean[key] = val
        else:
            msg = f"Metric {key}={val} out of range [{lim['min']}, {lim['max']}] — discarded"
            logger.warning(msg)
            if mqtt_pub and room_id:
                mqtt_pub.publish_alert(room_id, "abnormal_metric", key, msg)
    return clean


async def _fetch_predictions(room_id: str, base_url: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}/prediction/{room_id}")
            if resp.status_code == 200:
                body = resp.json()
                code = body.get("code")
                msg = body.get("msg", "")
                if code != 0:
                    logger.warning(f"Prediction service returned error code: {code}, details: {msg}")
                    return {}
                return body.get("data", {}).get("predictions")
    except Exception as e:
        logger.debug(f"Prediction service unavailable: {e}")
    return None


async def _fetch_all_rooms(catalog_url: str) -> list:
    """Fetch all room_ids from catalog service GET /rooms."""
    store = ss.get()
    cached = store.get_rooms()
    if cached:
        return cached
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{catalog_url}/rooms")
            if resp.status_code == 200:
                body = resp.json()
                if body.get("code") == 0:
                    rooms = [r["room_id"] for r in body.get("data", [])]
                    store.set_rooms(rooms)
                    return rooms
    except Exception as e:
        logger.error(f"Failed to fetch rooms from catalog: {e}")
    return []


async def _fetch_devices(catalog_url: str) -> list:
    """Fetch all devices from catalog GET /devices, cached in-memory."""
    store = ss.get()
    cached = store.get_devices()
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{catalog_url}/devices")
            if resp.status_code == 200:
                body = resp.json()
                if body.get("code") == 0:
                    devices = body.get("data", [])
                    store.set_devices(devices)
                    return devices
    except Exception as e:
        logger.error(f"Failed to fetch devices from catalog: {e}")
    return []


async def _fetch_room_config(room_id: str, catalog_url: str) -> Optional[dict]:
    store = ss.get()
    cached = store.get_config(room_id)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{catalog_url}/room/{room_id}")
            if resp.status_code == 200:
                body = resp.json()
                if body.get("code") == 0:
                    cfg = body["data"]
                    store.set_config(room_id, cfg)
                    return cfg
    except Exception as e:
        logger.error(f"Failed to fetch room config for {room_id}: {e}")
    return None


# ── Command timeout sweep ─────────────────────────────────────────────────────

def _check_command_timeouts(mqtt_pub, config: dict):
    """Alert and clear pending commands that exceeded the confirmation timeout."""
    timeout_s = config.get("command_confirmation", {}).get("timeout_s", 30)
    now = time.time()
    store = ss.get()
    for room_id, device_id, pending in store.get_all_pending_commands():
        if now - pending["command_timestamp"] > timeout_s:
            msg = (f"Command to set {device_id} → {pending['expected_state']} "
                   f"not confirmed within {timeout_s}s")
            logger.warning(msg)
            mqtt_pub.publish_alert(room_id, "command_timeout", device_id, msg)
            store.clear_pending_command(room_id, device_id)


# ── Prediction ──────────────────────────────────────────────────────
async def prediction_task(config: dict, mqtt_pub):
    interval = config["scheduler"]["prediction_interval"]

    while True:
        await asyncio.sleep(interval)

        try:
            catalog_url = config["services"]["catalog_base_url"]
            pred_url = config["services"]["prediction_base_url"]
            em_cfg = config.get("energy_mode", {})
            sm_timeout = config.get("state_machine", {}).get("transition_timeout", 10)

            # 3. Get all rooms from catalog
            rooms = await _fetch_all_rooms(catalog_url)

            for room_id in rooms:
                # Get latest metrics from In-Memory
                metrics_entry = ss.get().get_metrics(room_id)
                if not metrics_entry:
                    logger.debug(f"No metrics in store for room {room_id} — skipping")
                    continue
                metrics = metrics_entry["metrics"]

                # Fetch predictions
                predictions = await _fetch_predictions(room_id, pred_url)

                # Fetch room config
                room_cfg = await _fetch_room_config(room_id, catalog_url)
                if room_cfg is None:
                    logger.error(f"Cannot fetch room config for {room_id} — skipping")
                    continue

                policies = room_cfg.get("policies", [])
                conflict_rules = room_cfg.get("conflicts", [])
                energy_mode = room_cfg.get("energy_mode", "NORMAL")

                # 5. Evaluate policies → candidates
                candidates = policy_engine.evaluate(metrics, policies, predictions)

                # 6. Apply energy mode
                candidates = em.apply(candidates, energy_mode, metrics, em_cfg)

                # 7. Resolve conflicts
                final_actions, filtered_actions = conflict_resolver.resolve(candidates, conflict_rules)

                # 8. State machine transitions → commands
                commands = []
                for action in final_actions:
                    cmd = sm.transition(room_id, action["device"], action["state"], action.get("reason", "policy"), timeout=sm_timeout)
                    if cmd:
                        commands.append(cmd)

                # 9. Publish commands + record as pending for confirmation
                for cmd in commands:
                    mqtt_pub.publish_command(room_id, cmd["device_id"], cmd)
                    logger.info(f"Command published: room={room_id} device={cmd['device_id']} cmd={cmd['command']}")
                    ss.get().set_pending_command(
                        room_id, cmd["device_id"],
                        cmd.get("state", cmd.get("command", "")),
                        time.time(),
                    )

                # 10. Publish decision log
                mqtt_pub.publish_decision_log(
                    room_id=room_id,
                    decisions=[{"device_id": a["device"], "target": a["state"], "priority": a["priority"]} for a in final_actions],
                    filtered=[{"device_id": f["device"], "reason": f.get("filter_reason", "")} for f in filtered_actions],
                    energy_mode=energy_mode,
                    commands=[
                        {
                            "device_id": cmd["device_id"],
                            "command": cmd["command"],
                            "target_state": cmd.get("target_state"),
                            "reason": cmd.get("reason", ""),
                        }
                        for cmd in commands
                    ],
                )

        except Exception as e:
            traceback.print_exc()
            logger.warning(f"prediction task failed: {e}")

        _check_command_timeouts(mqtt_pub, config)
        logger.debug("decision cycle complete")
# ── Main pipeline ─────────────────────────────────────────────────────────────

async def process_sensor_event(event: dict, config: dict, mqtt_pub) -> None:
    room_id = event.get("room_id", "")
    timestamp = event.get("timestamp", 0)
    metrics: Dict[str, float] = event.get("metrics", {})

    # 1. Validate freshness
    now_ms = int(time.time() * 1000)
    freshness_limit = config.get("data_freshness_ms", 60000)
    if now_ms - timestamp > freshness_limit:
        logger.warning(f"Stale sensor event for room {room_id} — dropped")
        return

    # 2. Filter abnormal values
    metrics = _filter_abnormal(metrics, config.get("metric_limits", {}), room_id, mqtt_pub)
    if not metrics:
        logger.warning(f"No valid metrics for room {room_id} after filtering")
        return

    # 3. Store metrics to In-Memory
    ss.get().set_metrics(room_id, metrics, timestamp, event.get("meta", {}))
    logger.debug(f"Metrics stored for room {room_id}: {metrics}")


async def process_telemetry_event(topic: str, payload: dict, config: dict, mqtt_pub) -> None:
    """Handle airguard/{room_id}/telemetry/{device_type}/{device_id} messages."""
    parts = topic.split("/")
    if len(parts) < 5:
        logger.warning(f"Unexpected telemetry topic format: {topic}")
        return

    room_id = parts[1]
    device_id = payload.get("device_id", parts[4])
    value = payload.get("value")
    timestamp_s = payload.get("timestamp", 0)
    timestamp_ms = timestamp_s * 1000

    if value is None:
        logger.warning(f"No value in telemetry payload on topic {topic}")
        return

    # Look up device_class from catalog cache
    catalog_url = config["services"]["catalog_base_url"]
    devices = await _fetch_devices(catalog_url)
    device_info = next((d for d in devices if d["key"] == device_id), None)
    if device_info is None:
        logger.warning(f"Device {device_id} not found in catalog — skipping")
        return

    device_class = device_info["device_class"]

    # Store raw reading and recompute aggregated metrics for this room
    store = ss.get()
    store.update_raw_reading(room_id, device_id, device_class, float(value), timestamp_ms)
    metrics = store.get_aggregated_metrics(room_id)

    # Feed aggregated metrics into the existing pipeline
    event = {
        "room_id": room_id,
        "timestamp": timestamp_ms,
        "metrics": metrics,
    }
    await process_sensor_event(event, config, mqtt_pub)


async def process_device_feedback(topic: str, payload: dict, mqtt_pub=None, config: dict = None) -> None:
    """Handle device status messages.

    Supports both formats:
      - New: airguard/{room_id}/state/device/{device_id}
        Payload: {"device_id": str, "state": str, "timestamp": int (seconds)}
    """
    parts = topic.split("/")
    if topic.startswith("airguard/") and len(parts) >= 5:
        room_id = parts[1]
        device_id = parts[4]
    elif len(parts) >= 4:
        room_id = parts[1]
        device_id = parts[2]
    else:
        return

    reported_state = payload.get("state", "")
    result = payload.get("result", "ok")  # new format has no "result" field; treat as ok; Compatible with legacy code, currently has no practical use
    sm.handle_feedback(room_id, device_id, result, reported_state)

    # Command → feedback verification
    if mqtt_pub is None or config is None:
        return
    pending = ss.get().get_pending_command(room_id, device_id)
    if pending is None:
        return

    feedback_ts = payload.get("timestamp", 0)          # seconds
    command_ts = pending["command_timestamp"]           # time.time() float (seconds)
    expected_state = pending["expected_state"]
    confirm_window_s = (config.get("command_confirmation", {})
                        .get("confirm_window_s", 60))

    if reported_state == expected_state and 0 <= feedback_ts - command_ts <= confirm_window_s:
        logger.info(f"Command confirmed: room={room_id} device={device_id} state={reported_state}")
        ss.get().clear_pending_command(room_id, device_id)
    elif time.time() - command_ts > confirm_window_s:
        msg = (f"Command to set {device_id} → {expected_state} expired: "
               f"reported state={reported_state}")
        logger.warning(msg)
        mqtt_pub.publish_alert(room_id, "command_unconfirmed", device_id, msg)
        ss.get().clear_pending_command(room_id, device_id)


# ── Entry point ───────────────────────────────────────────────────────────────

async def start(config: dict, mqtt_pub):
    await asyncio.gather(
        prediction_task(config, mqtt_pub)
    )

