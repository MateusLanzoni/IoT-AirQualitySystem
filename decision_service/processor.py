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

                # 9. Publish commands
                for cmd in commands:
                    mqtt_pub.publish_command(room_id, cmd["device_id"], cmd)
                    logger.info(f"Command published: room={room_id} device={cmd['device_id']} cmd={cmd['command']}")

                # 10. Publish decision log
                mqtt_pub.publish_decision_log(
                    room_id=room_id,
                    decisions=[{"device_id": a["device"], "target": a["state"], "priority": a["priority"]} for a in final_actions],
                    filtered=[{"device_id": f["device"], "reason": f.get("filter_reason", "")} for f in filtered_actions],
                    energy_mode=energy_mode,
                )

        except Exception as e:
            traceback.print_exc()
            logger.warning(f"prediction task failed: {e}")

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
    metrics = _filter_abnormal(metrics, config.get("metric_limits", {}))
    if not metrics:
        logger.warning(f"No valid metrics for room {room_id} after filtering")
        return

    # 3. Store metrics to In-Memory
    ss.get().set_metrics(room_id, metrics, timestamp, event.get("meta", {}))
    logger.debug(f"Metrics stored for room {room_id}: {metrics}")


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

    
# ── Entry point ───────────────────────────────────────────────────────────────

async def start(config: dict, mqtt_pub):
    await asyncio.gather(
        prediction_task(config, mqtt_pub)
    )

