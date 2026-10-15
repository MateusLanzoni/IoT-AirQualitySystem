import asyncio
import logging
import threading

import cherrypy
import yaml

from components.adaptor.api import AdaptorAPI
from components.adaptor.egress_to_tspeak import start_egress
from components.adaptor.ingress_client import start_ingress
from components.registry.registry_client import CatalogRegistry
from env_loader import expand_env_values, load_env_file

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open("components/adaptor/config.yaml", "r") as f:
        return yaml.safe_load(f)


class BackgroundTaskManager:
    def __init__(self, config: dict):
        self._config = config
        self._loop = None
        self._thread = None
        self._tasks = []

    def start(self):
        self._loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()

        self._tasks.append(
            asyncio.run_coroutine_threadsafe(
                start_ingress(
                    broker_host="mosquitto",
                    port=1883,
                    topic_to_subscribe=["airguard/#", "sensor/#", "actuator/#"],
                ),
                self._loop,
            )
        )
        self._tasks.append(asyncio.run_coroutine_threadsafe(start_egress(self._config), self._loop))

    def stop(self):
        for task in self._tasks:
            task.cancel()

        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread is not None:
            self._thread.join(timeout=5)


def main():
    config = load_config()
    registry = CatalogRegistry()
    background_tasks = BackgroundTaskManager(config)

    logger.info("Loading configuration...")
    background_tasks.start()

    try:
        asyncio.run(registry.register())
    except Exception as exc:
        logger.error(f"Failed to register adaptor service: {exc}")

    root = AdaptorAPI()

    def on_stop():
        try:
            asyncio.run(registry.deregister())
        except Exception as exc:
            logger.error(f"Failed to deregister adaptor service: {exc}")
        background_tasks.stop()

    cherrypy.engine.subscribe("stop", on_stop)
    cherrypy.config.update(
        {
            "server.socket_host": "0.0.0.0",
            "server.socket_port": 8000,
        }
    )
    cherrypy.tree.mount(root, "/")

    logger.info("CherryPy adaptor service starting on 0.0.0.0:8000")
    cherrypy.engine.start()
    cherrypy.engine.block()


if __name__ == "__main__":
    main()