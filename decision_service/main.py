"""
Decision Service - main entry point.

Architecture:
  - FastAPI app for health + manual trigger endpoints
  - MQTT client runs in paho background thread
  - asyncio.Queue bridges MQTT thread → async processor
  - Processing pipeline: policy eval → energy mode → conflict → state machine → publish
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
import yaml
from fastapi import FastAPI

import state_store as ss
from mqtt_handler import MQTTHandler, MQTTPublisher
from processor import process_sensor_event, process_device_feedback

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


config = load_config()

# Module-level references set during startup
_mqtt_pub: MQTTPublisher = None
_mqtt_handler: MQTTHandler = None
_event_queue: asyncio.Queue = None


async def _dispatch_loop(queue: asyncio.Queue):
    """Async task: consume MQTT messages and dispatch to processor."""
    sensor_prefix = "sensor/"
    device_prefix = "device/"

    while True:
        topic, payload = await queue.get()
        try:
            if topic.startswith(sensor_prefix):
                await process_sensor_event(payload, config, _mqtt_pub)
            elif topic.startswith(device_prefix):
                await process_device_feedback(topic, payload)
        except Exception as e:
            logger.error(f"Error processing message [{topic}]: {e}")
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mqtt_pub, _mqtt_handler, _event_queue

    loop = asyncio.get_event_loop()
    _event_queue = asyncio.Queue()

    # Start MQTT (non-blocking, runs in paho thread)
    _mqtt_handler = MQTTHandler(config, _event_queue, loop)
    try:
        _mqtt_pub = _mqtt_handler.start()
        logger.info("MQTT client started")
    except Exception as e:
        logger.warning(f"MQTT unavailable: {e} — running without MQTT")
        _mqtt_pub = _DummyPublisher()

    # Start dispatch loop
    task = asyncio.create_task(_dispatch_loop(_event_queue))
    logger.info("Decision service started")

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if _mqtt_handler:
        _mqtt_handler.stop()
    logger.info("Decision service stopped")


class _DummyPublisher:
    """Fallback publisher when MQTT broker is unavailable."""
    def publish_command(self, *args, **kwargs):
        logger.info(f"[DUMMY MQTT] command: {args} {kwargs}")
    def publish_alert(self, *args, **kwargs):
        logger.info(f"[DUMMY MQTT] alert: {args} {kwargs}")
    def publish_decision_log(self, *args, **kwargs):
        logger.info(f"[DUMMY MQTT] decision_log: {args} {kwargs}")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Decision Service", 
    version="1.0.0", 
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "decision_service", "load": 0}


@app.get("/status")
def status():
    """Return current in-memory device states (debug endpoint)."""
    return {"code": 0, "msg": "success", "data": ss.get().get_all_states()}


@app.post("/trigger/{room_id}")
async def manual_trigger(room_id: str, body: dict):
    """
    Manually inject a sensor event for testing (bypasses MQTT).
    Body format mirrors MQTT sensor/{room_id}/state payload.
    """
    import time
    # Inject current timestamp if not provided
    if "timestamp" not in body:
        body["timestamp"] = int(time.time() * 1000)
    if "room_id" not in body:
        body["room_id"] = room_id

    await process_sensor_event(body, config, _mqtt_pub)
    return {"code": 0, "msg": "trigger processed", "data": None}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config["server"]["host"],
        port=config["server"]["port"],
        reload=False,
    )
