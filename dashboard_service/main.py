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


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

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
    return {
        "admin_fields": [
            {**field, "value": env_values.get(field["key"], os.getenv(field["key"], ""))}
            for field in ADMIN_ENV_FIELDS
        ],
        "dotenv_path": str(ROOT_DOTENV_PATH),
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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, room_id: str | None = None, message: str | None = None):
    current_user = _require_logged_in_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    room_id = room_id or get_default_room_id()
    context = await _collect_snapshot(room_id)
    context.update(
        request=request,
        current_user=current_user,
        is_admin=current_user.get("role") == "admin",
        admin_url="/admin/env",
        logout_url="/logout",
        register_url="/register",
        page_message=message,
    )
    return TEMPLATES.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/admin/env", response_class=HTMLResponse)
async def admin_env(request: Request, message: str | None = None, error: str | None = None):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    context = _admin_context()
    context["request"] = request
    context["current_user"] = current_user
    context["managed_users"] = auth_store.list_users_for_admin(int(current_user["id"]))
    context["dashboard_url"] = "/dashboard"
    context["logout_url"] = "/logout"
    context["message"] = message
    context["error"] = error
    return TEMPLATES.TemplateResponse(request=request, name="admin_env.html", context=context)


@app.post("/admin/env")
async def update_admin_env(request: Request, payload: AdminEnvUpdate):
    current_user = _require_admin_user(request)
    if isinstance(current_user, RedirectResponse):
        return current_user

    _authorize_admin(payload.password)
    updated_keys = _apply_env_updates(payload.values)
    return {"status": "ok", "updated": updated_keys, "dotenv_path": str(ROOT_DOTENV_PATH)}


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
