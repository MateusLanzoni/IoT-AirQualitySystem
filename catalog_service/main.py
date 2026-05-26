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
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI

import storage as st
import scheduler
from routers import router

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from env_loader import expand_env_values, load_env_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    load_env_file(Path(__file__).resolve().parent.parent / ".env")
    with open(path, "r", encoding="utf-8") as f:
        cfg = expand_env_values(yaml.safe_load(f))
    if os.getenv("SERVER_HOST"):
        cfg["server"]["host"] = os.getenv("SERVER_HOST")
    return cfg


config = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init storage
    st.init(config["data_dir"])
    logger.info("Storage loaded")

    # Start background tasks
    task = asyncio.create_task(scheduler.start(config))
    logger.info("Schedulers started")

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Catalog service stopped")


app = FastAPI(
    title="Catalog Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "catalog_service"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config["server"]["host"],
        port=config["server"]["port"],
        reload=False,
    )
