from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

DEFAULT_SERVICE_URLS = {
    "catalog": os.getenv("CATALOG_SERVICE_URL", "http://localhost:8001"),
    "prediction": os.getenv("PREDICTION_SERVICE_URL", "http://localhost:8003"),
    "decision": os.getenv("DECISION_SERVICE_URL", "http://localhost:8002"),
    "adaptor": os.getenv("ADAPTOR_SERVICE_URL", "http://localhost:8000"),
}

DEFAULT_ROOM_ID = os.getenv("DEFAULT_ROOM_ID", "room1")
DEFAULT_ADAPTOR_CONFIG_PATH = os.getenv(
    "ADAPTOR_CONFIG_PATH",
    os.path.join(os.path.dirname(BASE_DIR), "components", "adaptor", "config.yaml"),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=8.0)
    yield
    await app.state.http.aclose()


app = FastAPI(
    title="AirGuard Dashboard",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


async def _fetch_json(url: str) -> dict[str, Any] | list[Any] | None:
    try:
        response = await app.state.http.get(url)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _normalize_room_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"room[_-]?(\d+)", value)
    if match:
        return f"room{match.group(1)}"
    return value


def _load_thingspeak_rooms() -> list[dict[str, Any]]:
    config_path = Path(DEFAULT_ADAPTOR_CONFIG_PATH)
    if not config_path.is_file():
        return []

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    except Exception:
        return []

    discovery: list[dict[str, Any]] = []
    for channel in config.get("channels", []) or []:
        fields = channel.get("fields", {}) or {}
        field_values = [value for value in fields.values() if isinstance(value, str)]
        source_topic = next((value for value in field_values if value.startswith("airguard/")), None)
        room_id = _normalize_room_id(source_topic)
        kind = "command" if any("/command/" in value for value in field_values) else "telemetry"
        discovery.append(
            {
                "room_id": room_id or "unknown",
                "kind": kind,
                "channel_id": channel.get("channel_id"),
                "source_topic": source_topic,
                "fields": [
                    {"field": name, "topic": topic}
                    for name, topic in fields.items()
                    if isinstance(topic, str)
                ],
            }
        )

    return discovery


async def _collect_snapshot(room_id: str) -> dict[str, Any]:
    catalog = await _fetch_json(f"{DEFAULT_SERVICE_URLS['catalog']}/room/{room_id}")
    rooms = await _fetch_json(f"{DEFAULT_SERVICE_URLS['catalog']}/rooms")
    services = await _fetch_json(f"{DEFAULT_SERVICE_URLS['catalog']}/services")
    prediction = await _fetch_json(f"{DEFAULT_SERVICE_URLS['prediction']}/prediction/{room_id}")
    decision = await _fetch_json(f"{DEFAULT_SERVICE_URLS['decision']}/status")
    thingspeak_rooms = _load_thingspeak_rooms()

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=1)
    history_url = (
        f"{DEFAULT_SERVICE_URLS['adaptor']}/api/v1/history"
        f"?roomid={room_id}&starttime={start.strftime('%Y-%m-%dT%H:%M:%SZ')}&endtime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    history = await _fetch_json(history_url)

    room_data = catalog.get("data", {}) if isinstance(catalog, dict) else {}
    services_data = services.get("data", []) if isinstance(services, dict) else []
    decision_data = decision.get("data", {}) if isinstance(decision, dict) else {}
    prediction_data = prediction.get("data", {}) if isinstance(prediction, dict) else {}

    telemetry = history or []
    latest = telemetry[-1] if isinstance(telemetry, list) and telemetry else {}

    status_cards = {
        "catalog": {"label": "Catalog", "status": "online" if catalog else "offline"},
        "prediction": {"label": "Prediction", "status": "online" if prediction else "offline"},
        "decision": {"label": "Decision", "status": "online" if decision else "offline"},
        "adaptor": {"label": "Adaptor", "status": "online" if history else "offline"},
    }

    return {
        "room_id": room_id,
        "status_cards": status_cards,
        "room": room_data,
        "rooms": rooms.get("data", []) if isinstance(rooms, dict) else [],
        "services": services_data,
        "thingspeak_rooms": thingspeak_rooms,
        "prediction": prediction_data,
        "decision_states": decision_data,
        "history": telemetry,
        "latest": latest,
        "service_urls": DEFAULT_SERVICE_URLS,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "dashboard_service"}


@app.get("/api/snapshot")
async def snapshot(room_id: str = DEFAULT_ROOM_ID):
    return JSONResponse(await _collect_snapshot(room_id))


@app.get("/api/thingspeak-rooms")
async def thingspeak_rooms():
    rooms = _load_thingspeak_rooms()
    return JSONResponse({"count": len(rooms), "rooms": rooms})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, room_id: str = DEFAULT_ROOM_ID):
    context = await _collect_snapshot(room_id)
    context["request"] = request
    return TEMPLATES.TemplateResponse(request=request, name="index.html", context=context)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8501, reload=False)
