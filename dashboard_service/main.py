from __future__ import annotations

import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from env_loader import load_env_file, parse_env_file, write_env_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

ROOT_DOTENV_PATH = Path(
    os.getenv("ROOT_ENV_PATH", str(ROOT_DIR / ".env"))
)
load_env_file(ROOT_DOTENV_PATH, overwrite=True)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "paassword")

ADMIN_ENV_FIELDS = [
    {"key": "MQTT_USER", "label": "MQTT user", "kind": "text"},
    {"key": "MQTT_PASSWORD", "label": "MQTT password", "kind": "password"},
    {"key": "MQTT_PORT", "label": "MQTT port", "kind": "text"},
    {"key": "MQTT_BROKER", "label": "MQTT broker", "kind": "text"},
    {"key": "THINGSPEAK_WRITE_API_KEY", "label": "ThingSpeak write key", "kind": "password"},
    {"key": "THINGSPEAK_READ_API_KEY", "label": "ThingSpeak read key", "kind": "password"},
    {"key": "THINGSPEAK_COMMAND_WRITE_API_KEY", "label": "ThingSpeak command write key", "kind": "password"},
    {"key": "TELEGRAM_BOT_TOKEN", "label": "Telegram bot token", "kind": "password"},
    {"key": "TELEGRAM_CHAT_ID", "label": "Telegram chat id", "kind": "text"},
    {"key": "TELEGRAM_BOT_NAME", "label": "Telegram bot name", "kind": "text"},
    {"key": "ADMIN_PASSWORD", "label": "Admin password", "kind": "password"},
    {"key": "CATALOG_SERVICE_URL", "label": "Catalog service URL", "kind": "text"},
    {"key": "PREDICTION_SERVICE_URL", "label": "Prediction service URL", "kind": "text"},
    {"key": "DECISION_SERVICE_URL", "label": "Decision service URL", "kind": "text"},
    {"key": "ADAPTOR_SERVICE_URL", "label": "Adaptor service URL", "kind": "text"},
    {"key": "DEFAULT_ROOM_ID", "label": "Default room id", "kind": "text"},
]


class AdminEnvUpdate(BaseModel):
    password: str = Field(min_length=1)
    values: dict[str, str | None]

def get_service_urls() -> dict[str, str]:
    return {
        "catalog": os.getenv("CATALOG_SERVICE_URL", "http://localhost:8001"),
        "prediction": os.getenv("PREDICTION_SERVICE_URL", "http://localhost:8003"),
        "decision": os.getenv("DECISION_SERVICE_URL", "http://localhost:8002"),
        "adaptor": os.getenv("ADAPTOR_SERVICE_URL", "http://localhost:8000"),
    }


def get_default_room_id() -> str:
    return os.getenv("DEFAULT_ROOM_ID", "room1")


def get_adaptor_config_path() -> Path:
    return Path(
        os.getenv(
            "ADAPTOR_CONFIG_PATH",
            os.path.join(os.path.dirname(BASE_DIR), "components", "adaptor", "config.yaml"),
        )
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


def _reload_runtime_env() -> None:
    load_env_file(ROOT_DOTENV_PATH, overwrite=True)


def _admin_context() -> dict[str, Any]:
    _reload_runtime_env()
    env_values = parse_env_file(ROOT_DOTENV_PATH)
    return {
        "admin_fields": [
            {**field, "value": env_values.get(field["key"], os.getenv(field["key"], ""))}
            for field in ADMIN_ENV_FIELDS
        ],
        "dotenv_path": str(ROOT_DOTENV_PATH),
    }


def _normalize_room_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"room[_-]?(\d+)", value)
    if match:
        return f"room{match.group(1)}"
    return value


def _load_thingspeak_rooms() -> list[dict[str, Any]]:
    config_path = get_adaptor_config_path()
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


def _build_latest_sample(telemetry: list[dict[str, Any]]) -> dict[str, Any]:
    latest_fields = {"field2": "-", "field3": "-", "field4": "-", "field5": "-"}

    for row in reversed(telemetry):
        if not isinstance(row, dict):
            continue
        for field in latest_fields:
            value = row.get(field)
            if value not in (None, "") and latest_fields[field] == "-":
                latest_fields[field] = value

        if all(value != "-" for value in latest_fields.values()):
            break

    return latest_fields


async def _collect_snapshot(room_id: str) -> dict[str, Any]:
    _reload_runtime_env()
    service_urls = get_service_urls()
    catalog_health = await _fetch_json(f"{service_urls['catalog']}/health")
    prediction_health = await _fetch_json(f"{service_urls['prediction']}/health")
    decision_health = await _fetch_json(f"{service_urls['decision']}/health")
    adaptor_health = await _fetch_json(f"{service_urls['adaptor']}/health")
    catalog = await _fetch_json(f"{service_urls['catalog']}/room/{room_id}")
    rooms = await _fetch_json(f"{service_urls['catalog']}/rooms")
    services = await _fetch_json(f"{service_urls['catalog']}/services")
    prediction = await _fetch_json(f"{service_urls['prediction']}/prediction/{room_id}")
    decision = await _fetch_json(f"{service_urls['decision']}/status")
    thingspeak_rooms = _load_thingspeak_rooms()

    end = datetime.now(timezone.utc)
    recent_start = end - timedelta(hours=1)
    recent_history_url = (
        f"{service_urls['adaptor']}/api/v1/history"
        f"?roomid={room_id}&starttime={recent_start.strftime('%Y-%m-%dT%H:%M:%SZ')}&endtime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    history = await _fetch_json(recent_history_url)

    if not history:
        broad_start = end - timedelta(days=30)
        broad_history_url = (
            f"{service_urls['adaptor']}/api/v1/history"
            f"?roomid={room_id}&starttime={broad_start.strftime('%Y-%m-%dT%H:%M:%SZ')}&endtime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        history = await _fetch_json(broad_history_url)

    room_data = catalog.get("data", {}) if isinstance(catalog, dict) else {}
    services_data = services.get("data", []) if isinstance(services, dict) else []
    decision_data = decision.get("data", {}) if isinstance(decision, dict) else {}
    prediction_data = prediction.get("data", {}) if isinstance(prediction, dict) else {}

    telemetry = history or []
    latest = _build_latest_sample(telemetry) if isinstance(telemetry, list) else {}

    status_cards = {
        "catalog": {"label": "Catalog", "status": "online" if catalog_health else "offline"},
        "prediction": {"label": "Prediction", "status": "online" if prediction_health else "offline"},
        "decision": {"label": "Decision", "status": "online" if decision_health else "offline"},
        "adaptor": {"label": "Adaptor", "status": "online" if adaptor_health else "offline"},
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
        "service_urls": service_urls,
    }


def _authorize_admin(password: str) -> None:
    _reload_runtime_env()
    if password != os.getenv("ADMIN_PASSWORD", ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid admin password")


def _apply_env_updates(values: dict[str, str | None]) -> list[str]:
    _reload_runtime_env()
    current = parse_env_file(ROOT_DOTENV_PATH)
    updated_keys: list[str] = []

    for key, value in values.items():
        if value is None:
            continue
        cleaned = value.strip()
        if cleaned == "":
            continue
        current[key] = cleaned
        os.environ[key] = cleaned
        updated_keys.append(key)

    write_env_file(ROOT_DOTENV_PATH, current)
    return sorted(updated_keys)


@app.get("/health")
def health():
    return {"status": "ok", "service": "dashboard_service"}


@app.get("/api/snapshot")
async def snapshot(room_id: str | None = None):
    room_id = room_id or get_default_room_id()
    return JSONResponse(await _collect_snapshot(room_id))


@app.get("/api/thingspeak-rooms")
async def thingspeak_rooms():
    rooms = _load_thingspeak_rooms()
    return JSONResponse({"count": len(rooms), "rooms": rooms})


@app.get("/admin/env", response_class=HTMLResponse)
async def admin_env(request: Request):
    context = _admin_context()
    context["request"] = request
    return TEMPLATES.TemplateResponse(request=request, name="admin_env.html", context=context)


@app.post("/admin/env")
async def update_admin_env(payload: AdminEnvUpdate):
    _authorize_admin(payload.password)
    updated_keys = _apply_env_updates(payload.values)
    return {"status": "ok", "updated": updated_keys, "dotenv_path": str(ROOT_DOTENV_PATH)}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, room_id: str | None = None):
    room_id = room_id or get_default_room_id()
    context = await _collect_snapshot(room_id)
    context["request"] = request
    context["admin_url"] = "/admin/env"
    return TEMPLATES.TemplateResponse(request=request, name="index.html", context=context)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8501, reload=False)
