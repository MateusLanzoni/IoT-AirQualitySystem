from __future__ import annotations

import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from typing import Any

import httpx
import yaml
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import auth_store
from env_loader import load_env_file, parse_env_file, write_env_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

ROOT_DOTENV_PATH = Path(
    os.getenv("ROOT_ENV_PATH", str(ROOT_DIR / ".env"))
)
load_env_file(ROOT_DOTENV_PATH, overwrite=True)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "airguard-dev-session-secret")
DEFAULT_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", auth_store.DEFAULT_ADMIN_USERNAME)

ADMIN_ENV_FIELDS = [
    {"key": "MQTT_USER", "label": "MQTT user", "kind": "text", "group": "MQTT broker"},
    {"key": "MQTT_PASSWORD", "label": "MQTT password", "kind": "password", "group": "MQTT broker"},
    {"key": "MQTT_BROKER", "label": "MQTT broker host", "kind": "text", "group": "MQTT broker"},
    {"key": "MQTT_PORT", "label": "MQTT port", "kind": "text", "group": "MQTT broker"},
    {"key": "THINGSPEAK_WRITE_API_KEY", "label": "Write key", "kind": "password", "group": "ThingSpeak"},
    {"key": "THINGSPEAK_READ_API_KEY", "label": "Read key", "kind": "password", "group": "ThingSpeak"},
    {"key": "THINGSPEAK_COMMAND_WRITE_API_KEY", "label": "Command write key", "kind": "password", "group": "ThingSpeak"},
    {"key": "TELEGRAM_BOT_TOKEN", "label": "Bot token", "kind": "password", "group": "Telegram"},
    {"key": "TELEGRAM_CHAT_ID", "label": "Chat id", "kind": "text", "group": "Telegram"},
    {"key": "TELEGRAM_BOT_NAME", "label": "Bot name", "kind": "text", "group": "Telegram"},
    {"key": "CATALOG_SERVICE_URL", "label": "Catalog service URL", "kind": "text", "group": "Service URLs"},
    {"key": "PREDICTION_SERVICE_URL", "label": "Prediction service URL", "kind": "text", "group": "Service URLs"},
    {"key": "DECISION_SERVICE_URL", "label": "Decision service URL", "kind": "text", "group": "Service URLs"},
    {"key": "ADAPTOR_SERVICE_URL", "label": "Adaptor service URL", "kind": "text", "group": "Service URLs"},
    {"key": "DEFAULT_ROOM_ID", "label": "Default room id", "kind": "text", "group": "Dashboard"},
    {"key": "ADMIN_PASSWORD", "label": "New admin password", "kind": "password", "group": "Dashboard"},
]

# Air-quality metrics shown on the dashboard. `field` is the ThingSpeak field
# used by the adaptor history API; `bands` are (good, moderate) limits, anything
# outside the moderate band is rated poor.
METRICS = [
    {
        "key": "temperature", "label": "Temperature", "field": "field2", "unit": "°C", "decimals": 1,
        "good": (20, 26), "moderate": (18, 28), "target": "Comfort range 20–26 °C",
    },
    {
        "key": "humidity", "label": "Humidity", "field": "field3", "unit": "%", "decimals": 0,
        "good": (30, 60), "moderate": (25, 70), "target": "Comfort range 30–60 %",
    },
    {
        "key": "co2", "label": "CO₂", "field": "field4", "unit": "ppm", "decimals": 0,
        "good": (0, 800), "moderate": (0, 1000), "target": "Good below 800 ppm",
    },
    {
        "key": "pm25", "label": "PM2.5", "field": "field5", "unit": "µg/m³", "decimals": 1,
        "good": (0, 15), "moderate": (0, 35), "target": "WHO guideline ≤ 15 µg/m³",
    },
]
METRICS_BY_KEY = {metric["key"]: metric for metric in METRICS}
STATUS_LABELS = {"good": "Good", "warn": "Moderate", "bad": "Poor"}
DEVICE_CLASS_LABELS = {
    "temperature": "Temperature", "humidity": "Humidity", "co2": "CO₂", "pm25": "PM2.5",
    "AC": "Air conditioner", "FAN": "Fan", "WINDOW": "Window",
}
POLICY_OPERATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


class AdminEnvUpdate(BaseModel):
    password: str = Field(min_length=1)
    values: dict[str, str | None]


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


ALLOWED_POLICY_OPERATORS = set(POLICY_OPERATORS)

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
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    same_site="lax",
    https_only=False,
)

auth_store.initialize_database(admin_username=DEFAULT_ADMIN_USERNAME, admin_password=ADMIN_PASSWORD)


async def _fetch_json(url: str) -> dict[str, Any] | list[Any] | None:
    try:
        response = await app.state.http.get(url)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _reload_runtime_env() -> None:
    load_env_file(ROOT_DOTENV_PATH, overwrite=True)


def _sync_admin_password_if_needed(updated_keys: list[str]) -> None:
    if "ADMIN_PASSWORD" in updated_keys:
        auth_store.sync_admin_password(DEFAULT_ADMIN_USERNAME, os.getenv("ADMIN_PASSWORD", ADMIN_PASSWORD))


def _message_url(path: str, message: str | None = None, error: str | None = None) -> str:
    params: list[str] = []
    if message:
        params.append(f"message={quote(message)}")
    if error:
        params.append(f"error={quote(error)}")
    if params:
        return f"{path}?{'&'.join(params)}"
    return path


def _get_current_user(request: Request) -> dict[str, Any] | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return auth_store.get_user_by_id(int(user_id))


def _redirect_to_login(message: str | None = None, error: str | None = None) -> RedirectResponse:
    return RedirectResponse(_message_url("/login", message=message, error=error), status_code=303)


def _redirect_to_dashboard(message: str | None = None) -> RedirectResponse:
    return RedirectResponse(_message_url("/dashboard", message=message), status_code=303)


def _require_logged_in_user(request: Request) -> dict[str, Any] | RedirectResponse:
    current_user = _get_current_user(request)
    if current_user is None:
        return _redirect_to_login()
    return current_user


def _require_admin_user(request: Request) -> dict[str, Any] | RedirectResponse:
    current_user = _get_current_user(request)
    if current_user is None:
        return _redirect_to_login()
    if current_user.get("role") != "admin":
        return _redirect_to_dashboard(message="Admin access required.")
    return current_user


def _admin_context() -> dict[str, Any]:
    _reload_runtime_env()
    env_values = parse_env_file(ROOT_DOTENV_PATH)
    groups: dict[str, list[dict[str, Any]]] = {}
    for field in ADMIN_ENV_FIELDS:
        current = env_values.get(field["key"], os.getenv(field["key"], "")) or ""
        is_secret = field["kind"] == "password"
        groups.setdefault(field["group"], []).append({
            **field,
            # Secrets are never sent to the browser; a blank submit keeps the current value.
            "value": "" if is_secret else current,
            "is_set": bool(current),
        })
    return {
        "admin_groups": groups,
        "dotenv_path": str(ROOT_DOTENV_PATH),
    }


def _build_policy_id(room_id: str, metric: str, operator: str, value: float, target_device: str) -> str:
    raw = f"{room_id}_{metric}_{operator}_{value}_{target_device}"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"policy_{slug}_{stamp}"


def _normalize_policy_value(value: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Target value must be numeric.") from exc


async def _catalog_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    service_urls = get_service_urls()
    response = await app.state.http.post(f"{service_urls['catalog']}{path}", json=payload)
    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and body.get("code", 1) != 0:
        raise HTTPException(status_code=400, detail=body.get("msg", "Catalog request failed"))
    return body


async def _catalog_delete(path: str) -> dict[str, Any]:
    service_urls = get_service_urls()
    response = await app.state.http.delete(f"{service_urls['catalog']}{path}")
    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and body.get("code", 1) != 0:
        raise HTTPException(status_code=400, detail=body.get("msg", "Catalog request failed"))
    return body


async def _catalog_put(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    service_urls = get_service_urls()
    response = await app.state.http.put(f"{service_urls['catalog']}{path}", json=payload)
    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and body.get("code", 1) != 0:
        raise HTTPException(status_code=400, detail=body.get("msg", "Catalog request failed"))
    return body


def _csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def _management_data() -> dict[str, Any]:
    service_urls = get_service_urls()
    rooms = await _fetch_json(f"{service_urls['catalog']}/rooms")
    devices = await _fetch_json(f"{service_urls['catalog']}/devices")
    policies = await _fetch_json(f"{service_urls['catalog']}/policies")
    room_list = (rooms.get("data") or []) if isinstance(rooms, dict) else []
    device_list = (devices.get("data") or []) if isinstance(devices, dict) else []
    policy_list = (policies.get("data") or []) if isinstance(policies, dict) else []
    known_keys = {device.get("key") for device in device_list}
    for room in room_list:
        # Deleting a room leaves these behind, so the confirm dialog mentions them.
        room["assigned_device_count"] = sum(1 for device in device_list if device.get("room_id") == room.get("room_id"))
        room["policy_count"] = sum(1 for policy in policy_list if policy.get("room_id") == room.get("room_id"))
        listed = set(room.get("device_ids") or [])
        # Flag drift between a room's device list and the devices that point at it.
        room["unlisted_devices"] = sorted(
            device["key"] for device in device_list
            if device.get("room_id") == room.get("room_id") and device.get("key") not in listed
        )
        room["unknown_devices"] = sorted(key for key in listed if key not in known_keys)
    return {
        "rooms": room_list,
        "devices": device_list,
        "policies": policy_list,
        "metrics": METRICS,
        "metrics_by_key": METRICS_BY_KEY,
        "device_class_labels": DEVICE_CLASS_LABELS,
    }


def _render_login_context(request: Request, message: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "request": request,
        "message": message,
        "error": error,
    }


def _render_register_context(request: Request, message: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "request": request,
        "message": message,
        "error": error,
        "admins": auth_store.list_admins(),
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


async def _fetch_room_history(room_id: str, adaptor_url: str, lookback_hours: int = 24) -> list[dict[str, Any]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    history_url = (
        f"{adaptor_url}/api/v1/history"
        f"?roomid={room_id}&starttime={start.strftime('%Y-%m-%dT%H:%M:%SZ')}&endtime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    history = await _fetch_json(history_url)
    if isinstance(history, list):
        return [row for row in history if isinstance(row, dict)]
    if isinstance(history, dict):
        points = history.get("points", history.get("items", []))
        if isinstance(points, list):
            return [row for row in points if isinstance(row, dict)]
    return []


async def _enrich_thingspeak_rooms(
    rooms: list[dict[str, Any]], adaptor_url: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    history_by_room: dict[str, list[dict[str, Any]]] = {}
    for room in rooms:
        item = dict(room)
        room_id = item.get("room_id", "unknown")
        if item.get("kind") != "telemetry":
            item["telemetry"] = []
            item["history_points"] = 0
            enriched.append(item)
            continue
        if room_id not in history_by_room:
            history_by_room[room_id] = await _fetch_room_history(room_id, adaptor_url)

        history = history_by_room.get(room_id, [])
        fields: list[dict[str, Any]] = []
        for field in item.get("fields", []):
            value = None
            timestamp = None
            for row in reversed(history):
                candidate = row.get(field["field"])
                if candidate not in (None, ""):
                    value = candidate
                    timestamp = row.get("created_at", row.get("timestamp"))
                    break
            fields.append({
                **field,
                "value": value if value not in (None, "") else "-",
                "timestamp": timestamp,
            })
        item["telemetry"] = fields
        item["history_points"] = len(history)
        enriched.append(item)
    return enriched


def _parse_time(value: Any) -> datetime | None:
    """Accept ISO strings, epoch seconds or epoch milliseconds."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _iso(value: Any) -> str | None:
    parsed = _parse_time(value)
    return parsed.isoformat() if parsed else None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float | None, decimals: int) -> str:
    if value is None:
        return "–"
    return f"{value:.{decimals}f}"


def _format_span(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"{minutes} min"
    hours = round(minutes / 60)
    if hours < 48:
        return f"{hours} h"
    return f"{round(hours / 24)} days"


def _classify(metric: dict[str, Any], value: float | None) -> str | None:
    if value is None:
        return None
    low, high = metric["good"]
    if low <= value <= high:
        return "good"
    low, high = metric["moderate"]
    if low <= value <= high:
        return "warn"
    return "bad"


def _sparkline(
    points: list[tuple[datetime, float]],
    forecast: tuple[datetime, float] | None,
    width: int = 200,
    height: int = 48,
) -> dict[str, str] | None:
    if len(points) < 2:
        return None
    series = points + ([forecast] if forecast else [])
    t0 = series[0][0].timestamp()
    t1 = max(moment.timestamp() for moment, _ in series)
    values = [value for _, value in series]
    low, high = min(values), max(values)
    if high - low < 1e-9:
        low, high = low - 1, high + 1
    pad = (high - low) * 0.15
    low, high = low - pad, high + pad

    def xy(moment: datetime, value: float) -> tuple[float, float]:
        x = (moment.timestamp() - t0) / ((t1 - t0) or 1) * width
        y = height - (value - low) / (high - low) * height
        return round(x, 1), round(y, 1)

    # Break the line where readings stop for a while instead of drawing a
    # straight segment across the gap as if data existed there.
    steps = sorted((b[0] - a[0]).total_seconds() for a, b in zip(points, points[1:]))
    gap = max(steps[len(steps) // 2] * 4, 300)
    segments: list[list[tuple[float, float]]] = [[xy(*points[0])]]
    for previous, current in zip(points, points[1:]):
        if (current[0] - previous[0]).total_seconds() > gap:
            segments.append([])
        segments[-1].append(xy(*current))

    def path(coords: list[tuple[float, float]]) -> str:
        return "M" + " L".join(f"{x},{y}" for x, y in coords)

    line = " ".join(path(coords) for coords in segments)
    area = " ".join(
        f"{path(coords)} L{coords[-1][0]},{height} L{coords[0][0]},{height} Z"
        for coords in segments if len(coords) > 1
    )
    coords = segments[-1]
    result = {"line": line, "area": area, "width": str(width), "height": str(height),
              "end_x": str(coords[-1][0]), "end_y": str(coords[-1][1])}
    if forecast:
        fx, fy = xy(*forecast)
        result.update(forecast=f"{coords[-1][0]},{coords[-1][1]} {fx},{fy}", forecast_x=str(fx), forecast_y=str(fy))
    return result


def _build_metric_cards(history: list[dict[str, Any]], prediction: dict[str, Any]) -> list[dict[str, Any]]:
    rows = sorted(
        (row for row in history if isinstance(row, dict) and _parse_time(row.get("created_at"))),
        key=lambda row: _parse_time(row.get("created_at")),
    )
    predictions = (prediction.get("predictions") or {}) if isinstance(prediction, dict) else {}
    cards: list[dict[str, Any]] = []
    for metric in METRICS:
        points = [
            (_parse_time(row["created_at"]), value)
            for row in rows
            if (value := _to_float(row.get(metric["field"]))) is not None
        ]
        value = points[-1][1] if points else None
        status = _classify(metric, value)

        forecast = None
        info = predictions.get(metric["key"]) or {}
        forecast_value = _to_float(info.get("value"))
        if forecast_value is not None and points:
            horizon = int(info.get("horizon_minutes") or 15)
            generated = _parse_time(info.get("generated_at")) or points[-1][0]
            target_time = max(generated, points[-1][0]) + timedelta(minutes=horizon)
            forecast = (target_time, forecast_value)

        trend = None
        if len(points) >= 2:
            delta = points[-1][1] - points[0][1]
            trend = {
                "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
                "delta": _format_number(abs(delta), metric["decimals"]),
                "span": _format_span((points[-1][0] - points[0][0]).total_seconds()),
            }

        cards.append({
            "key": metric["key"],
            "label": metric["label"],
            "unit": metric["unit"],
            "value": _format_number(value, metric["decimals"]),
            "has_value": value is not None,
            "status": status,
            "status_label": STATUS_LABELS.get(status or "", "No data"),
            "target": metric["target"],
            "updated_at": points[-1][0].isoformat() if points else None,
            "trend": trend,
            "forecast": _format_number(forecast_value, metric["decimals"]) if forecast_value is not None else None,
            "forecast_status": _classify(metric, forecast_value),
            "horizon": int(info.get("horizon_minutes") or 15) if info else None,
            "spark": _sparkline(points, forecast),
        })
    return cards


def _metric_for_device_class(device_class: str | None) -> dict[str, Any] | None:
    return METRICS_BY_KEY.get((device_class or "").lower())


def _build_device_rows(
    room: dict[str, Any], decision_states: dict[str, Any], room_id: str, cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cards_by_key = {card["key"]: card for card in cards}
    room_states = decision_states.get(room_id, {}) if isinstance(decision_states, dict) else {}
    rows: list[dict[str, Any]] = []
    for device in room.get("sensors", []) or []:
        metric = _metric_for_device_class(device.get("device_class"))
        card = cards_by_key.get(metric["key"]) if metric else None
        rows.append({
            "key": device.get("key") or device.get("name"),
            "kind": "sensor",
            "type": DEVICE_CLASS_LABELS.get(device.get("device_class"), device.get("device_class") or "Sensor"),
            "reading": f"{card['value']} {card['unit']}" if card and card["has_value"] else "No data",
            "status": card["status"] if card else None,
            "updated_at": card["updated_at"] if card else None,
        })
    seen: set[str] = set()
    for device in room.get("actuators", []) or []:
        key = device.get("key") or device.get("name")
        seen.add(key)
        entry = room_states.get(key) or {}
        rows.append(_actuator_row(key, device.get("device_class"), entry))
    for key, entry in room_states.items():
        if key not in seen:
            rows.append(_actuator_row(key, None, entry))
    return rows


def _actuator_row(key: str, device_class: str | None, entry: dict[str, Any]) -> dict[str, Any]:
    state = str(entry.get("state") or "").upper()
    if state == "ERROR":
        status = "bad"
    elif state in {"ON", "OPEN"}:
        status = "active"
    else:
        status = "idle" if state else None
    return {
        "key": key,
        "kind": "actuator",
        "type": DEVICE_CLASS_LABELS.get(device_class or "", device_class or "Actuator"),
        "reading": state or "No command yet",
        "status": status,
        "updated_at": _iso(entry.get("last_action_time")),
    }


def _build_policy_rows(room: dict[str, Any], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = {card["key"]: _to_float(card["value"]) for card in cards}
    rows: list[dict[str, Any]] = []
    for policy in sorted(room.get("policies", []) or [], key=lambda item: item.get("priority", 99)):
        metric = METRICS_BY_KEY.get(str(policy.get("metric", "")).lower())
        current = values.get(metric["key"]) if metric else None
        threshold = _to_float(policy.get("value"))
        compare = POLICY_OPERATORS.get(policy.get("operator"))
        active = bool(compare and current is not None and threshold is not None and compare(current, threshold))
        rows.append({
            "policy_id": policy.get("policy_id"),
            "metric": metric["label"] if metric else policy.get("metric"),
            "operator": policy.get("operator"),
            "value": f"{policy.get('value')} {metric['unit']}" if metric else policy.get("value"),
            "target_device": policy.get("target_device"),
            "target_state": policy.get("target_state"),
            "priority": policy.get("priority"),
            "active": active,
        })
    return rows


def _label_thingspeak_fields(channels: list[dict[str, Any]], devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    devices_by_key = {device.get("key"): device for device in devices if isinstance(device, dict)}
    labelled: list[dict[str, Any]] = []
    for channel in channels:
        item = dict(channel)
        fields = []
        for field in item.get("telemetry") or item.get("fields", []):
            topic = field.get("topic") or ""
            device_key = topic.rsplit("/", 1)[-1] if "/device/" in topic else None
            device = devices_by_key.get(device_key) if device_key else None
            if device:
                label = DEVICE_CLASS_LABELS.get(device.get("device_class"), device.get("device_class"))
                metric = _metric_for_device_class(device.get("device_class"))
                unit = metric["unit"] if metric else ""
            elif device_key:
                label, unit = device_key, ""
            else:
                label, unit = "Room id", ""
            fields.append({
                **field,
                "label": label,
                "device": device_key,
                "unit": unit,
                "timestamp": _iso(field.get("timestamp")),
            })
        item["labelled_fields"] = fields
        labelled.append(item)
    return labelled


TEMPLATES.env.filters["iso"] = _iso


async def _collect_snapshot(room_id: str) -> dict[str, Any]:
    _reload_runtime_env()
    service_urls = get_service_urls()
    catalog_health = await _fetch_json(f"{service_urls['catalog']}/health")
    prediction_health = await _fetch_json(f"{service_urls['prediction']}/health")
    decision_health = await _fetch_json(f"{service_urls['decision']}/health")
    adaptor_health = await _fetch_json(f"{service_urls['adaptor']}/health")
    catalog = await _fetch_json(f"{service_urls['catalog']}/room/{room_id}")
    rooms = await _fetch_json(f"{service_urls['catalog']}/rooms")
    devices = await _fetch_json(f"{service_urls['catalog']}/devices")
    services = await _fetch_json(f"{service_urls['catalog']}/services")
    decision = await _fetch_json(f"{service_urls['decision']}/status")
    thingspeak_rooms = await _enrich_thingspeak_rooms(
        _load_thingspeak_rooms(), service_urls["adaptor"]
    )

    # `or` rather than a .get() default: services answer {"data": null} for unknown ids.
    room_data = (catalog.get("data") or {}) if isinstance(catalog, dict) else {}

    # Only rooms that exist in the catalog get readings and a forecast; anything
    # else is shown as "no data".
    prediction = None
    history = None
    if room_data:
        prediction = await _fetch_json(f"{service_urls['prediction']}/prediction/{room_id}")
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

    services_data = (services.get("data") or []) if isinstance(services, dict) else []
    decision_data = (decision.get("data") or {}) if isinstance(decision, dict) else {}
    prediction_data = (prediction.get("data") or {}) if isinstance(prediction, dict) else {}
    devices_data = (devices.get("data") or []) if isinstance(devices, dict) else []

    telemetry = history if isinstance(history, list) else []
    latest = _build_latest_sample(telemetry)
    metric_cards = _build_metric_cards(telemetry, prediction_data)
    updated_at = max((card["updated_at"] for card in metric_cards if card["updated_at"]), default=None)

    status_cards = {
        "catalog": {"label": "Catalog", "status": "online" if catalog_health else "offline"},
        "prediction": {"label": "Prediction", "status": "online" if prediction_health else "offline"},
        "decision": {"label": "Decision", "status": "online" if decision_health else "offline"},
        "adaptor": {"label": "Adaptor", "status": "online" if adaptor_health else "offline"},
    }

    return {
        "room_id": room_id,
        "room_found": bool(room_data),
        "status_cards": status_cards,
        "room": room_data,
        "rooms": (rooms.get("data") or []) if isinstance(rooms, dict) else [],
        "services": services_data,
        "thingspeak_rooms": _label_thingspeak_fields(thingspeak_rooms, devices_data),
        "prediction": prediction_data,
        "decision_states": decision_data,
        "history": telemetry,
        "latest": latest,
        "metric_cards": metric_cards,
        "has_readings": any(card["has_value"] for card in metric_cards),
        "device_rows": _build_device_rows(room_data, decision_data, room_id, metric_cards),
        "policy_rows": _build_policy_rows(room_data, metric_cards),
        "updated_at": updated_at,
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
        if cleaned == "" or current.get(key) == cleaned:
            continue
        current[key] = cleaned
        os.environ[key] = cleaned
        updated_keys.append(key)

    write_env_file(ROOT_DOTENV_PATH, current)
    _sync_admin_password_if_needed(updated_keys)
    return sorted(updated_keys)


@app.get("/health")
def health():
    return {"status": "ok", "service": "dashboard_service"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, message: str | None = None, error: str | None = None):
    if _get_current_user(request):
        return _redirect_to_dashboard()
    context = _render_login_context(request, message=message, error=error)
    return TEMPLATES.TemplateResponse(request=request, name="login.html", context=context)


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = auth_store.authenticate_user(username.strip(), password)
    if user is None:
        context = _render_login_context(request, error="Invalid username or password.")
        return TEMPLATES.TemplateResponse(request=request, name="login.html", context=context, status_code=401)

    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    return _redirect_to_dashboard(message=f"Welcome, {user['username']}.")


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, message: str | None = None, error: str | None = None):
    if _get_current_user(request):
        return _redirect_to_dashboard()
    context = _render_register_context(request, message=message, error=error)
    return TEMPLATES.TemplateResponse(request=request, name="register.html", context=context)


@app.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    admin_username: str = Form(...),
):
    admin_user = auth_store.get_user_by_username(admin_username.strip())
    if admin_user is None or admin_user.get("role") != "admin" or not admin_user.get("is_active"):
        context = _render_register_context(request, error="Select a valid active admin.")
        return TEMPLATES.TemplateResponse(request=request, name="register.html", context=context, status_code=400)

    try:
        auth_store.create_user(username.strip(), password, int(admin_user["id"]))
    except ValueError as exc:
        context = _render_register_context(request, error=str(exc))
        return TEMPLATES.TemplateResponse(request=request, name="register.html", context=context, status_code=400)

    return _redirect_to_login(message="Account created. You can log in now.")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return _redirect_to_login(message="You have been logged out.")


@app.get("/api/snapshot")
async def snapshot(room_id: str | None = None):
    room_id = room_id or get_default_room_id()
    return JSONResponse(await _collect_snapshot(room_id))


@app.get("/api/thingspeak-rooms")
async def thingspeak_rooms():
    rooms = _load_thingspeak_rooms()
    return JSONResponse({"count": len(rooms), "rooms": rooms})


@app.get("/api/thingspeak-rooms/{room_id}/telemetry")
async def thingspeak_room_telemetry(room_id: str):
    _reload_runtime_env()
    service_urls = get_service_urls()
    rooms = [room for room in _load_thingspeak_rooms() if room.get("room_id") == room_id]
    enriched = await _enrich_thingspeak_rooms(rooms, service_urls["adaptor"])
    return JSONResponse({"room_id": room_id, "rooms": enriched})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, room_id: str | None = None, message: str | None = None):
    current_user = _require_logged_in_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    if not room_id:
        # Fall back to the first catalog room when the default one was deleted.
        room_id = get_default_room_id()
        rooms = await _fetch_json(f"{get_service_urls()['catalog']}/rooms")
        room_ids = [room.get("room_id") for room in ((rooms.get("data") or []) if isinstance(rooms, dict) else [])]
        if room_ids and room_id not in room_ids:
            room_id = room_ids[0]
    context = await _collect_snapshot(room_id)
    context.update(
        request=request,
        current_user=current_user,
        is_admin=current_user.get("role") == "admin",
        page_message=message,
    )
    return TEMPLATES.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/admin/env", response_class=HTMLResponse)
async def admin_env(request: Request, message: str | None = None, error: str | None = None):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    context = _admin_context()
    context.update(
        request=request,
        current_user=current_user,
        is_admin=True,
        managed_users=auth_store.list_users_for_admin(int(current_user["id"])),
        message=message,
        error=error,
    )
    return TEMPLATES.TemplateResponse(request=request, name="admin_env.html", context=context)


@app.get("/admin/management", response_class=HTMLResponse)
async def admin_management(request: Request, message: str | None = None, error: str | None = None):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    context = await _management_data()
    context.update(
        request=request,
        current_user=current_user,
        is_admin=True,
        message=message,
        error=error,
    )
    return TEMPLATES.TemplateResponse(request=request, name="admin_management.html", context=context)


@app.post("/admin/env")
async def update_admin_env(request: Request, payload: AdminEnvUpdate):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    _authorize_admin(payload.password)
    updated_keys = _apply_env_updates(payload.values)
    return {"status": "ok", "updated": updated_keys, "dotenv_path": str(ROOT_DOTENV_PATH)}


@app.post("/admin/targets/create")
async def admin_create_target(
    request: Request,
    room_id: str = Form(...),
    metric: str = Form(...),
    operator: str = Form(...),
    value: str = Form(...),
    target_device: str = Form(...),
    target_state: str = Form(...),
    priority: int = Form(1),
    policy_id: str | None = Form(None),
):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    room_value = room_id.strip() or get_default_room_id()
    metric_value = metric.strip().lower()
    operator_value = operator.strip()
    target_device_value = target_device.strip()
    target_state_value = target_state.strip().upper()

    if operator_value not in ALLOWED_POLICY_OPERATORS:
        return RedirectResponse(_message_url("/admin/env", error="Unsupported target operator."), status_code=303)

    if not target_device_value:
        return RedirectResponse(_message_url("/admin/env", error="Target device is required."), status_code=303)

    payload = {
        "policy_id": policy_id.strip() if policy_id and policy_id.strip() else _build_policy_id(room_value, metric_value, operator_value, _normalize_policy_value(value), target_device_value),
        "room_id": room_value,
        "metric": metric_value,
        "operator": operator_value,
        "value": _normalize_policy_value(value),
        "target_device": target_device_value,
        "target_state": target_state_value,
        "priority": priority,
    }

    try:
        await _catalog_post("/policies", payload)
    except HTTPException as exc:
        return RedirectResponse(_message_url("/admin/env", error=str(exc.detail)), status_code=303)
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/env", error=f"Unable to save target: {exc}"), status_code=303)

    return RedirectResponse(_message_url("/admin/env", message="Target saved."), status_code=303)


@app.post("/admin/targets/{policy_id}/delete")
async def admin_delete_target(request: Request, policy_id: str):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    try:
        await _catalog_delete(f"/policies/{policy_id}")
    except HTTPException as exc:
        return RedirectResponse(_message_url("/admin/env", error=str(exc.detail)), status_code=303)
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/env", error=f"Unable to delete target: {exc}"), status_code=303)

    return RedirectResponse(_message_url("/admin/env", message="Target deleted."), status_code=303)


@app.post("/admin/management/rooms/create")
async def admin_create_room(
    request: Request,
    room_id: str = Form(...),
    device_ids: str = Form(""),
    energy_mode: str = Form("NORMAL"),
    schedule_start: str = Form("08:00"),
    schedule_end: str = Form("23:00"),
):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    payload = {
        "room_id": room_id.strip(),
        "device_ids": _csv_values(device_ids),
        "energy_mode": energy_mode.strip().upper(),
        "schedule": {"start": schedule_start.strip(), "end": schedule_end.strip()},
    }
    try:
        await _catalog_post("/rooms", payload)
        message = "Room created."
    except Exception as exc:
        message = f"Unable to create room: {getattr(exc, 'detail', exc)}"
        return RedirectResponse(_message_url("/admin/management", error=message), status_code=303)
    return RedirectResponse(_message_url("/admin/management", message=message), status_code=303)


@app.post("/admin/management/rooms/{room_id}/update")
async def admin_update_room(
    request: Request,
    room_id: str,
    device_ids: str = Form(""),
    energy_mode: str = Form("NORMAL"),
    schedule_start: str = Form("08:00"),
    schedule_end: str = Form("23:00"),
):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    payload = {
        "device_ids": _csv_values(device_ids),
        "energy_mode": energy_mode.strip().upper(),
        "schedule": {"start": schedule_start.strip(), "end": schedule_end.strip()},
    }
    try:
        await _catalog_put(f"/rooms/{room_id}", payload)
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/management", error=f"Unable to update room: {getattr(exc, 'detail', exc)}"), status_code=303)
    return RedirectResponse(_message_url("/admin/management", message=f"Room {room_id} updated."), status_code=303)


@app.post("/admin/management/rooms/{room_id}/delete")
async def admin_delete_room(request: Request, room_id: str):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    try:
        await _catalog_delete(f"/rooms/{room_id}")
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/management", error=f"Unable to delete room: {getattr(exc, 'detail', exc)}"), status_code=303)
    return RedirectResponse(_message_url("/admin/management", message=f"Room {room_id} deleted."), status_code=303)


@app.post("/admin/management/devices/{device_id}/update")
async def admin_update_device(
    request: Request,
    device_id: str,
    name: str = Form(...),
    device_class: str = Form(...),
    category: str = Form(...),
    room_id: str = Form(...),
    unit: str = Form(""),
):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    payload = {
        "key": device_id,
        "name": name.strip(),
        "device_class": device_class.strip(),
        "category": category.strip().lower(),
        "room_id": room_id.strip(),
        "unit": unit.strip(),
    }
    try:
        await _catalog_put(f"/devices/{device_id}", payload)
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/management", error=f"Unable to update device: {getattr(exc, 'detail', exc)}"), status_code=303)
    return RedirectResponse(_message_url("/admin/management", message=f"Device {device_id} updated."), status_code=303)


@app.post("/admin/management/policies/create")
async def admin_management_create_policy(
    request: Request,
    room_id: str = Form(...),
    metric: str = Form(...),
    operator: str = Form(...),
    value: str = Form(...),
    target_device: str = Form(...),
    target_state: str = Form(...),
    priority: int = Form(1),
    policy_id: str | None = Form(None),
):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    if operator not in ALLOWED_POLICY_OPERATORS:
        return RedirectResponse(_message_url("/admin/management", error="Unsupported policy operator."), status_code=303)
    threshold = _normalize_policy_value(value)
    payload = {
        "policy_id": (policy_id or "").strip() or _build_policy_id(room_id.strip(), metric.strip().lower(), operator, threshold, target_device.strip()),
        "room_id": room_id.strip(),
        "metric": metric.strip().lower(),
        "operator": operator,
        "value": threshold,
        "target_device": target_device.strip(),
        "target_state": target_state.strip().upper(),
        "priority": priority,
    }
    try:
        await _catalog_post("/policies", payload)
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/management", error=f"Unable to create policy: {getattr(exc, 'detail', exc)}"), status_code=303)
    return RedirectResponse(_message_url("/admin/management", message="Policy created."), status_code=303)


@app.post("/admin/management/policies/{policy_id}/update")
async def admin_update_policy(
    request: Request,
    policy_id: str,
    metric: str = Form(...),
    operator: str = Form(...),
    value: str = Form(...),
    target_device: str = Form(...),
    target_state: str = Form(...),
    priority: int = Form(1),
):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    if operator not in ALLOWED_POLICY_OPERATORS:
        return RedirectResponse(_message_url("/admin/management", error="Unsupported policy operator."), status_code=303)
    payload = {
        "metric": metric.strip().lower(),
        "operator": operator,
        "value": _normalize_policy_value(value),
        "target_device": target_device.strip(),
        "target_state": target_state.strip().upper(),
        "priority": priority,
    }
    try:
        await _catalog_put(f"/policies/{policy_id}", payload)
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/management", error=f"Unable to update policy: {getattr(exc, 'detail', exc)}"), status_code=303)
    return RedirectResponse(_message_url("/admin/management", message=f"Policy {policy_id} updated."), status_code=303)


@app.post("/admin/management/policies/{policy_id}/delete")
async def admin_management_delete_policy(request: Request, policy_id: str):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user
    try:
        await _catalog_delete(f"/policies/{policy_id}")
    except Exception as exc:
        return RedirectResponse(_message_url("/admin/management", error=f"Unable to delete policy: {getattr(exc, 'detail', exc)}"), status_code=303)
    return RedirectResponse(_message_url("/admin/management", message=f"Policy {policy_id} deleted."), status_code=303)


@app.post("/admin/users/create")
async def admin_create_user(request: Request, username: str = Form(...), password: str = Form(...)):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    try:
        auth_store.create_user(username.strip(), password, int(current_user["id"]))
    except ValueError as exc:
        return RedirectResponse(
            _message_url("/admin/env", error=str(exc)),
            status_code=303,
        )

    return RedirectResponse(_message_url("/admin/env", message="User created."), status_code=303)


@app.post("/admin/users/{user_id}/toggle")
async def admin_toggle_user(request: Request, user_id: int, enabled: str = Form(...)):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    target_enabled = enabled.lower() in {"1", "true", "yes", "on"}
    try:
        auth_store.set_user_active(user_id, target_enabled, admin_id=int(current_user["id"]))
    except ValueError as exc:
        return RedirectResponse(
            _message_url("/admin/env", error=str(exc)),
            status_code=303,
        )

    action = "enabled" if target_enabled else "disabled"
    return RedirectResponse(_message_url("/admin/env", message=f"User {action}."), status_code=303)


@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(request: Request, user_id: int):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    try:
        auth_store.delete_user(user_id, admin_id=int(current_user["id"]))
    except ValueError as exc:
        return RedirectResponse(
            _message_url("/admin/env", error=str(exc)),
            status_code=303,
        )

    return RedirectResponse(_message_url("/admin/env", message="User deleted."), status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if _get_current_user(request):
        return _redirect_to_dashboard()
    return _redirect_to_login()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8501, reload=False)
