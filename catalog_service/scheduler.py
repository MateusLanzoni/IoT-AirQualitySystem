"""
Background schedulers:
  1. Heartbeat puller  - mock ThingSpeak pull every N seconds
  2. Health checker    - ping registered services every N seconds
  3. Auto-offline      - mark stale devices/services offline (runs with heartbeat)
"""
import asyncio
import logging
import random
import time

import httpx

import storage as st

logger = logging.getLogger(__name__)


# ── Heartbeat (mock ThingSpeak pull) ─────────────────────────────────────────

def _mock_thingspeak_pull(device_id: str, dev_type: str) -> dict:
    """Return simulated sensor reading or actuator state."""
    if dev_type == "temperature":
        return {"key": device_id, "status": "online", "value": round(random.uniform(22, 32), 1)}
    if dev_type == "co2":
        return {"key": device_id, "status": "online", "value": round(random.uniform(600, 1400), 1)}
    if dev_type == "humidity":
        return {"key": device_id, "status": "online", "value": round(random.uniform(40, 80), 1)}
    # actuators - just report current actual_state
    return None


async def heartbeat_task(config: dict):
    interval = config["scheduler"]["heartbeat_interval"]
    offline_timeout = config["scheduler"]["offline_timeout"]
    mock_mode = config["thingspeak"].get("mock_mode", True)

    while True:
        await asyncio.sleep(interval)
        store = st.get()
        if store is None:
            continue

        for device_id, dev in list(store.devices.items()):
            try:
                if mock_mode:
                    update = _mock_thingspeak_pull(device_id, dev.get("type", ""))
                else:
                    # Real ThingSpeak fetch would go here
                    update = None

                if update:
                    store.heartbeat_device(device_id, update)
            except Exception as e:
                logger.warning(f"Heartbeat failed for {device_id}: {e}")

        # Auto-offline sweep
        store.sweep_offline(offline_timeout)
        store.sweep_services_offline(offline_timeout)
        logger.debug("Heartbeat cycle complete")


# ── Service Health Check ──────────────────────────────────────────────────────

async def health_check_task(config: dict):
    interval = config["scheduler"]["health_check_interval"]
    request_timeout = 1.0

    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(interval)
            store = st.get()
            if store is None:
                continue

            for svc_id, svc in list(store.services.items()):
                url = svc.get("endpoint", "") + svc.get("health_endpoint", "/health")
                try:
                    resp = await client.get(url, timeout=request_timeout)
                    if resp.status_code == 200:
                        svc["status"] = "online"
                        svc["last_seen"] = int(time.time())
                        body = resp.json()
                        if "load" in body:
                            svc["load"] = body["load"]
                    else:
                        svc["status"] = "degraded"
                except Exception:
                    svc["status"] = "offline"

            store.save_services()
            logger.debug("Health check cycle complete")


# ── Entry point ───────────────────────────────────────────────────────────────

async def start(config: dict):
    await asyncio.gather(
        heartbeat_task(config),
        health_check_task(config),
    )
