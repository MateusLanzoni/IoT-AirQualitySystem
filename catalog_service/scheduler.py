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
import requests
import traceback

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

# ── Heartbeat (reall ThingSpeak pull) ─────────────────────────────────────────

def get_thingspeak_feeds(base_url, results=100, api_key=None):
    """
    get feeds data from ThingSpeak - read feeds data from a channel

    params:
        base_url (str): the base URL for the ThingSpeak API endpoint, e.g. "https://api.thingspeak.com/channels/{channel_id}/feeds.json"
        results (int): results count (default 100, max 8000)
        api_key (str): read API key if channel is private (optional)

    returns:
        list: feeds list, each feed is a dict with fields like "created_at", "entry_id", "field1", "field2", etc.
    """

    url = base_url

    params = {
        "results": results
    }

    # private channel requires api_key
    if api_key:
        params["api_key"] = api_key

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()  # HTTP failure will raise an exception

        data = response.json()

        # get feeds
        feeds = data.get("feeds", [])

        return feeds

    except requests.exceptions.RequestException as e:
        print(f"request failed: {e}")
        return []
    except ValueError:
        print("JSON parsing failed")
        return []

def handle_device_channel_feed(feeds, channel_config):
    result = {}

    if not feeds:
        return result

    # get the latest feed entry
    latest_feed = feeds[-1]

    fields_config = channel_config.get("fields", {})

    for field, meta in fields_config.items():
        value = latest_feed.get(field)
        if value is None:
            continue
        try:
            if value.replace('.', '', 1).isdigit():
                value = float(value) if '.' in value else int(value)
        except:
            pass

        device_id = meta.get("device_id", field)
        result[device_id] = {
            "name": meta.get("name", ""),
            "value": value
        }

    return result


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
                    store.heartbeat_device(device_id, update)
                else:
                    # Real ThingSpeak fetch would go here
                    ts_cfg = config["thingspeak"]

                    channel_id = ts_cfg["channel"]["id"]
                    channel_config = ts_cfg["channel"]["fields"]
                    url_template = ts_cfg["base_url"]
                    results = ts_cfg.get("results", 1)
                    api_key = ts_cfg.get("api_key")
                    url = url_template.format(channel_id=channel_id)
                    feeds = get_thingspeak_feeds(
                        url,
                        results, 
                        api_key
                    )
                    devices = handle_device_channel_feed(feeds, channel_config)
                    for dev_id, data in devices.items():
                        update = {"value": data["value"]}
                        store.heartbeat_device(dev_id, update)
            except Exception as e:
                traceback.print_exc()
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
