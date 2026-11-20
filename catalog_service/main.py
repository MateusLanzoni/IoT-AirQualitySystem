"""
Catalog Service - main entry point.

Startup:
  1. Load config.yaml
  2. Init storage (load JSON → in-memory cache)
  3. Launch background schedulers (heartbeat + health check)
  4. Mount all routers
"""
import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

import cherrypy
import yaml

from routers import build_app
import storage as st
import scheduler


ROOT_DIR = Path(__file__).resolve().parents[0]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def load_config(path: Path = ROOT_DIR / "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if os.getenv("SERVER_HOST"):
        cfg["server"]["host"] = os.getenv("SERVER_HOST")
    return cfg

config = load_config()

logging.basicConfig(
    level=config.get("log_level", "WARNING"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def start_scheduler() -> None:
    asyncio.run(scheduler.start(config))


if __name__ == "__main__":
    st.init(ROOT_DIR / config["data_dir"], config)
    threading.Thread(target=start_scheduler, name="catalog-scheduler", daemon=True).start()
    logger.info("Schedulers started")
    cherrypy.config.update({
        "server.socket_host": config["server"]["host"],
        "server.socket_port": config["server"]["port"],
    })
    root, conf = build_app()
    cherrypy.quickstart(root, "/", conf)
