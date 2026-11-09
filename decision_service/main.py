"""
Decision Service - main entry point.

Architecture:
  - CherryPy app for health + manual trigger endpoints
  - MQTT client runs in paho background thread
  - asyncio.Queue bridges MQTT thread → async processor
  - Processing pipeline: policy eval → energy mode → conflict → state machine → publish

"""
import asyncio
import json
import logging
import threading

import cherrypy
from load_config import load_config

import state_store as ss
from mqtt_handler import MQTTHandler, MQTTPublisher
from processor import process_sensor_event, process_telemetry_event, process_device_feedback, start as scheduler_start

from mock import MockService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)



config = load_config()

# Module-level references set during startup
_mqtt_pub: MQTTPublisher = None
_mqtt_handler: MQTTHandler = None
_event_queue: asyncio.Queue = None
_loop: asyncio.AbstractEventLoop = None
_loop_thread: threading.Thread = None
_dispatch_task: asyncio.Task = None
_scheduler_task: asyncio.Task = None


async def _dispatch_loop(queue: asyncio.Queue):
    """Async task: consume MQTT messages and dispatch to processor."""
    while True:
        topic, payload = await queue.get()
        try:
            if topic.startswith("sensor/"):
                await process_sensor_event(payload, config, _mqtt_pub)
            elif "/telemetry/" in topic:
                await process_telemetry_event(topic, payload, config, _mqtt_pub)
            elif "/state/" in topic or topic.startswith("device/"):
                await process_device_feedback(topic, payload, _mqtt_pub, config)
        except Exception as e:
            logger.error(f"Error processing message [{topic}]: {e}")
        finally:
            queue.task_done()


class _DummyPublisher:
    """Fallback publisher when MQTT broker is unavailable."""
    def publish_command(self, *args, **kwargs):
        logger.info(f"[DUMMY MQTT] command: {args} {kwargs}")
    def publish_alert(self, *args, **kwargs):
        logger.info(f"[DUMMY MQTT] alert: {args} {kwargs}")
    def publish_decision_log(self, *args, **kwargs):
        logger.info(f"[DUMMY MQTT] decision_log: {args} {kwargs}")
    def publish_decision_log(self, *args, **kwargs):
        logger.info(f"[DUMMY MQTT] mock_log: {args} {kwargs}")


# ── Lifecycle (replaces FastAPI lifespan) ─────────────────────────────────────

async def _startup():
    global _mqtt_pub, _mqtt_handler, _event_queue, _dispatch_task, _scheduler_task

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
    _dispatch_task = asyncio.create_task(_dispatch_loop(_event_queue))
    _scheduler_task = asyncio.create_task(scheduler_start(config, _mqtt_pub))
    logger.info("Decision service started")


async def _shutdown():
    _dispatch_task.cancel()
    _scheduler_task.cancel()
    try:
        await asyncio.gather(_dispatch_task, _scheduler_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    if _mqtt_handler:
        _mqtt_handler.stop()
    logger.info("Decision service stopped")


def _run_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def on_start():
    """Start the asyncio loop thread and run the startup coroutine."""
    global _loop, _loop_thread
    _loop = asyncio.new_event_loop()
    _loop_thread = threading.Thread(target=_run_loop, args=(_loop,), name="asyncio-loop", daemon=True)
    _loop_thread.start()
    asyncio.run_coroutine_threadsafe(_startup(), _loop).result()


def on_stop():
    """Run the shutdown coroutine and stop the asyncio loop thread."""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_shutdown(), _loop).result()
    _loop.call_soon_threadsafe(_loop.stop)
    _loop_thread.join(timeout=5)


def _run_async(coro):
    """Run a coroutine on the background event loop and wait for its result."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


SWAGGER_API = {
    "openapi": "3.0.3",
    "info": {"title": "Decision Service", "version": "1.0.0"},
    "paths": {
        "/health": {"get": {"summary": "Health check", "responses": {"200": {"description": "OK"}}}},
        "/status": {"get": {"summary": "Current device states", "responses": {"200": {"description": "OK"}}}},
        "/trigger/{room_id}": {"post": {
            "summary": "Manually inject a sensor event",
            "parameters": [{"name": "room_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
            "responses": {"200": {"description": "OK"}},
        }},
        "/mock/start": {"get": {"summary": "Start mock data", "responses": {"200": {"description": "OK"}}}},
        "/mock/stop": {"get": {"summary": "Stop mock data", "responses": {"200": {"description": "OK"}}}},
    },
}

DOCS_HTML = """<!doctype html><html><head><title>Decision Service - Docs</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url: '/openapi.json', dom_id: '#ui'})</script></body></html>"""


   
# ── CherryPy app ──────────────────────────────────────────────────────────────

class MockApi:
    """/mock/start and /mock/stop"""

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def start(self):
        """Return a mock service object for testing."""
        mock_service = MockService()
        mock_service.run(5, mqtt_pub=_mqtt_pub)
        return 0

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def stop(self):
        """Return a mock service object for testing."""
        mock_service = MockService()
        mock_service.stop()
        return 0


class DecisionService:
    mock = MockApi()

    @cherrypy.expose
    def docs(self):
        return DOCS_HTML

    @cherrypy.expose(alias="openapi.json")
    @cherrypy.tools.json_out()
    def swagger(self):
        return SWAGGER_API
    
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def health(self):
        return {"status": "ok", "service": "decision_service", "load": 0}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def status(self):
        """Return current in-memory device states (debug endpoint)."""
        return {
            "code": 0,
            "msg": "success",
            "data": ss.get().get_all_states(),
            "metrics": ss.get().get_all_metrics(),
        }

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    @cherrypy.tools.allow(methods=["POST"])
    def trigger(self, room_id):
        """
        Manually inject a sensor event for testing (bypasses MQTT).
        Body format mirrors MQTT sensor/{room_id}/state payload.
        """
        import time
        body = cherrypy.request.json
        if not isinstance(body, dict):
            raise cherrypy.HTTPError(422, "JSON object body required")
        # Inject current timestamp if not provided
        if "timestamp" not in body:
            body["timestamp"] = int(time.time() * 1000)
        if "room_id" not in body:
            body["room_id"] = room_id

        _run_async(process_sensor_event(body, config, _mqtt_pub))
        return {"code": 0, "msg": "trigger processed", "data": None}


if __name__ == "__main__":
    cherrypy.config.update({
        "server.socket_host": config["server"]["host"],
        "server.socket_port": config["server"]["port"],
        "engine.autoreload.on": False,
    })
    cherrypy.engine.subscribe("start", on_start)
    cherrypy.engine.subscribe("stop", on_stop)
    cherrypy.quickstart(DecisionService(), "/")
