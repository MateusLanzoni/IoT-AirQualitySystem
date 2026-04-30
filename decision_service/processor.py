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
import logging
import time
from typing import Dict, List, Optional

import httpx

import policy_engine
import energy_mode as em
import conflict_resolver
import state_machine as sm
import state_store as ss

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _filter_abnormal(metrics: Dict[str, float], limits: dict) -> Dict[str, float]:
    """Remove metric values outside configured min/max bounds."""
    clean = {}
    for key, val in metrics.items():
        lim = limits.get(key)
        if lim is None:
            clean[key] = val
            continue
        if lim["min"] <= val <= lim["max"]:
            clean[key] = val
        else:
            logger.warning(f"Metric {key}={val} out of range [{lim['min']}, {lim['max']}] — discarded")
    return clean


async def _fetch_predictions(room_id: str, base_url: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}/prediction/{room_id}")
            if resp.status_code == 200:
                body = resp.json()
                return body.get("data", {}).get("predictions")
    except Exception as e:
        logger.debug(f"Prediction service unavailable: {e}")
    return None


async def _fetch_room_config(room_id: str, catalog_url: str, config_cache_ttl: int) -> Optional[dict]:
    store = ss.get()
    cached = store.get_config(room_id, config_cache_ttl)
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
    metrics = _filter_abnormal(metrics, config.get("metric_limits", {}))
    if not metrics:
        logger.warning(f"No valid metrics for room {room_id} after filtering")
        return

    # TODO: triggered by device status or prediction service?
    # 3. Fetch predictions (best-effort)
    pred_url = config["services"]["prediction_base_url"]
    predictions = await _fetch_predictions(room_id, pred_url)

    # 4. Fetch room config
    catalog_url = config["services"]["catalog_base_url"]
    ttl = config.get("config_cache_ttl", 60)
    room_cfg = await _fetch_room_config(room_id, catalog_url, ttl)
    if room_cfg is None:
        logger.error(f"Cannot fetch room config for {room_id} — aborting")
        return

    policies = room_cfg.get("policies", [])
    conflict_rules = room_cfg.get("conflicts", [])
    energy_mode = room_cfg.get("energy_mode", "NORMAL")
    em_cfg = config.get("energy_mode", {})
    sm_timeout = config.get("state_machine", {}).get("transition_timeout", 10)

    # 5. Evaluate policies → candidates
    candidates = policy_engine.evaluate(metrics, policies, predictions)

    # 6. Apply energy mode
    candidates = em.apply(candidates, energy_mode, metrics, em_cfg)

    # 7. Resolve conflicts
    final_actions, filtered_actions = conflict_resolver.resolve(candidates, conflict_rules)

    # 8. State machine transitions → commands
    commands = []
    for action in final_actions:
        device_id = action["device"]
        target_state = action["state"]
        reason = action.get("reason", "policy")
        cmd = sm.transition(room_id, device_id, target_state, reason, timeout=sm_timeout)
        if cmd:
            commands.append(cmd)

    # 9. Publish commands
    for cmd in commands:
        device_id = cmd["device_id"]
        mqtt_pub.publish_command(room_id, device_id, cmd)
        logger.info(f"Command published: room={room_id} device={device_id} cmd={cmd['command']}")

    # 10. Publish decision log
    mqtt_pub.publish_decision_log(
        room_id=room_id,
        decisions=[{"device_id": a["device"], "target": a["state"], "priority": a["priority"]} for a in final_actions],
        filtered=[{"device_id": f["device"], "reason": f.get("filter_reason", "")} for f in filtered_actions],
        energy_mode=energy_mode,
    )


async def process_device_feedback(topic: str, payload: dict) -> None:
    """Handle device/{room_id}/{device_id}/status messages."""
    parts = topic.split("/")
    if len(parts) < 4:
        return
    room_id = parts[1]
    device_id = parts[2]
    result = payload.get("result", "")
    reported_state = payload.get("state", "")
    sm.handle_feedback(room_id, device_id, result, reported_state)
