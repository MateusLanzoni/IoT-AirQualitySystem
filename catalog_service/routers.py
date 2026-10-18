import functools
import json
import time

import cherrypy

import storage as st

from schemas import (
    DeviceDTO, HeartbeatSensorDTO, HeartbeatActuatorDTO,
    RoomCreateDTO, RoomUpdateDTO,
    PolicyCreateDTO, PolicyUpdateDTO,
    ConflictCreateDTO, ConflictUpdateDTO,
    ServiceRegisterDTO,
    ok, err,
)


def _json_response(response: dict) -> bytes:
    cherrypy.response.headers["Content-Type"] = "application/json"
    cherrypy.response.headers["Access-Control-Allow-Origin"] = "*"
    return json.dumps(response).encode("utf-8")


def _request_body() -> dict:
    raw = cherrypy.request.body.read()
    return json.loads(raw) if raw else {}


def _json_error_page(status, message, traceback, version):
    """Global error page: always return JSON (err format), never HTML."""
    cherrypy.response.headers["Content-Type"] = "application/json"
    code = int(str(status).split()[0])
    return json.dumps(err(message or str(status), code=code)).encode("utf-8")


def _swagger_api() -> dict:
    def op(summary, body=None, path_param=None, query=None):
        o = {"summary": summary, "responses": {"200": {"description": "OK"}}}
        params = []
        if path_param:
            params.append({"name": path_param, "in": "path", "required": True,
                           "schema": {"type": "string"}})
        for q in (query or []):
            params.append({"name": q, "in": "query", "required": False,
                           "schema": {"type": "string"}})
        if params:
            o["parameters"] = params
        if body:
            o["requestBody"] = {"required": True, "content": {"application/json": {
                "schema": {"$ref": f"#/components/schemas/{body.__name__}"}}}}
        return o

    models = [DeviceDTO, RoomCreateDTO, RoomUpdateDTO, PolicyCreateDTO,
              PolicyUpdateDTO, ConflictCreateDTO, ConflictUpdateDTO, ServiceRegisterDTO]
    schemas = {}
    for m in models:
        s = m.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(s.pop("$defs", {}))
        schemas[m.__name__] = s

    return {
        "openapi": "3.0.3",
        "info": {"title": "Catalog Service API", "version": "1.0"},
        "paths": {
            "/devices": {
                "get": op("List devices"),
                "post": op("Create device", DeviceDTO)
            },
            "/devices/{device_id}": {
                "put": op("Update device", DeviceDTO, "device_id"),
                "delete": op("Delete device", path_param="device_id")},
            "/rooms": {"get": op("List rooms"), "post": op("Create room", RoomCreateDTO)},
            "/rooms/{room_id}": {
                "get": op("Get room", path_param="room_id"),
                "put": op("Update room", RoomUpdateDTO, "room_id"),
                "delete": op("Delete room", path_param="room_id")},
            "/policies": {
                "get": op("List policies", query=["room_id"]),
                "post": op("Create policy", PolicyCreateDTO)},
            "/policies/{policy_id}": {
                "put": op("Update policy", PolicyUpdateDTO, "policy_id"),
                "delete": op("Delete policy", path_param="policy_id")},
            "/conflicts": {
                "get": op("List conflicts", query=["room_id"]),
                "post": op("Create conflict", ConflictCreateDTO)},
            "/conflicts/{conflict_id}": {
                "put": op("Update conflict", ConflictUpdateDTO, "conflict_id"),
                "delete": op("Delete conflict", path_param="conflict_id")},
            "/services": {"get": op("List services")},
            "/services/register": {"post": op("Register service", ServiceRegisterDTO)},
            "/services/{service_id}": {
                "delete": op("Delete service", path_param="service_id")},
            "/room/{room_id}": {"get": op("Room aggregate", path_param="room_id")},
        },
        "components": {"schemas": schemas},
    }


# ── Validation helpers: return err(...) on failure, None on success ──────────

def verify_device(device_ids):
    missing = [d for d in device_ids if d not in st.get().devices]
    if missing:
        return err(f"Devices not found: {missing}", code=404)


def _normalize_device_class(value):
    types = {t.lower(): t for t in st.get().get_config().get("DEVICE_TYPES", [])}
    return types.get((value or "").strip().lower()), list(types.values())


def _normalize_category(value):
    cats = {c.lower() for c in st.get().get_config().get("DEVICE_CATEGORIES", [])}
    v = (value or "").strip().lower()
    return (v if v in cats else None), sorted(cats)


def verify_device_class(value):
    normalized, types = _normalize_device_class(value)
    if normalized is None:
        return err(f"device_class/metrics must be one of {types}", code=400)


def verify_strategy(strategy):
    allowed = {t.lower() for t in st.get().get_config().get("STRATEGIES", [])}
    if (strategy or "").strip().lower() not in allowed:
        return err(f"strategy must be one of {sorted(allowed)}", code=400)


def _device_to_dto(dev: dict) -> dict:
    return {
        "key": dev["device_id"],
        "name": dev["device_name"],
        "device_class": dev.get("type", ""),
        "category": dev.get("category", ""),
        "room_id": dev.get("room_id", ""),
        "unit": dev.get("unit", ""),
    }


def get_room(room_id: str):
    store = st.get()
    room = store.rooms.get(room_id)
    if room is None:
        return err(f"Room {room_id} not found", code=404)
    return ok(room)


SWAGGER_UI = """<!doctype html><html><head><title>Catalog Service API</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>window.onload = function () {
  SwaggerUIBundle({ spec: __SPEC__, dom_id: "#swagger-ui" });
};</script></body></html>"""


def _api(fn):

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            result = fn(self, *args, **kwargs)
        except cherrypy.HTTPError as exc:            # NotFound
            cherrypy.response.status = exc.code
            return _json_response(err(exc._message or exc.reason, code=exc.code))
        except (ValueError, TypeError) as exc:       # pydantic ValidationError
            cherrypy.response.status = 400
            return _json_response(err(str(exc), code=400))
        except Exception as exc:
            cherrypy.log(f"unhandled error: {exc!r}", traceback=True)
            cherrypy.response.status = 500
            return _json_response(err("Internal server error", code=500))

        if isinstance(result, dict) and isinstance(result.get("code"), int) and result["code"] >= 400:
            cherrypy.response.status = result["code"]
        return _json_response(result)
    return wrapper


class Resource:
    exposed = True   # MethodDispatcher requires exposed = True

    def OPTIONS(self, *args, **kwargs):          # CORS
        cherrypy.response.status = 204
        h = cherrypy.response.headers
        h["Access-Control-Allow-Origin"] = "*"
        h["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        h["Access-Control-Allow-Headers"] = "Content-Type"
        return b""


class Root:
    pass


class Docs(Resource):
    def GET(self):
        spec = json.dumps(_swagger_api()).replace("</", "<\\/")
        cherrypy.response.headers["Content-Type"] = "text/html; charset=utf-8"
        return SWAGGER_UI.replace("__SPEC__", spec).encode("utf-8")


class Health(Resource):
    @_api
    def GET(self):
        return {"status": "ok", "service": "catalog_service"}


class Devices(Resource):
    def create_update_device(self, device_id: str, body: DeviceDTO, msg: str):
        store = st.get()

        device_type, types = _normalize_device_class(body.device_class)
        if device_type is None:
            return err(f"device_class must be one of {types}", code=400)
        category, cats = _normalize_category(body.category)
        if category is None:
            return err(f"category must be one of {cats}", code=400)

        if body.room_id and body.room_id not in store.rooms:
            return err(f"Room {body.room_id} not found", code=404)

        existing = store.devices.get(device_id, {})
        existing.update({
            "device_id": device_id,
            "device_name": body.name,
            "type": device_type,
            "category": category,
            "room_id": body.room_id,
            "unit": body.unit,
            "created": existing.get("created", int(time.time())),
            "metadata": existing.get("metadata", {}),
        })
        store.upsert_device(device_id, existing)
        return ok(None, msg)

    @_api
    def GET(self):
        store = st.get()
        dtos = [_device_to_dto(d) for d in store.devices.values()]
        return ok(dtos)

    @_api
    def POST(self):
        body = DeviceDTO.model_validate(_request_body())

        if body.key is None:
            return err("key is required", code=400)

        return self.create_update_device(body.key, body, "created")

    @_api
    def PUT(self, device_id):
        body = DeviceDTO.model_validate(_request_body())
        if body.key is None:
            body.key = device_id
        if body.key != device_id:
            return err("key must match device_id", code=400)

        return self.create_update_device(device_id, body, "updated")

    @_api
    def DELETE(self, device_id):
        store = st.get()
        if not store.delete_device(device_id):
            return err(f"Device {device_id} not found", code=404)
        return ok(None, "deleted")


class Rooms(Resource):

    def _energy_modes(self) -> dict:
        cfg = st.get().get_config()
        return {m.upper(): m for m in cfg.get("ENERGY_MODES", [])}

    def _normalize_energy_mode(self, value: str):
        """Normalize energy mode to canonical form, or return None if invalid."""
        return self._energy_modes().get((value or "NORMAL").strip().upper())

    def create_room(self, body: RoomCreateDTO):
        store = st.get()
        if body.room_id in store.rooms:
            return err(f"Room {body.room_id} already exists", code=409)

        mode = self._normalize_energy_mode(body.energy_mode)
        if mode is None:
            return err(f"energy_mode must be one of {list(self._energy_modes().values())}", code=400)

        error = verify_device(body.device_ids)
        if error:
            return error

        room = body.model_dump()
        room["energy_mode"] = mode
        store.rooms[body.room_id] = room
        store.save_rooms()
        return ok(None, "created")

    @_api
    def GET(self, room_id=None):
        if room_id is not None:
            return get_room(room_id)

        store = st.get()
        return ok(list(store.rooms.values()))

    @_api
    def POST(self):
        body = RoomCreateDTO.model_validate(_request_body())
        return self.create_room(body)

    @_api
    def PUT(self, room_id):
        body = RoomUpdateDTO.model_validate(_request_body())
        store = st.get()
        room = store.rooms.get(room_id)
        if room is None:
            return err(f"Room {room_id} not found", code=404)

        # validate everything first, then apply
        mode = None
        if body.device_ids is not None:
            error = verify_device(body.device_ids)
            if error:
                return error
        if body.energy_mode is not None:
            mode = self._normalize_energy_mode(body.energy_mode)
            if mode is None:
                return err(f"energy_mode must be one of {list(self._energy_modes().values())}", code=400)

        if body.device_ids is not None:
            room["device_ids"] = body.device_ids
        if mode is not None:
            room["energy_mode"] = mode
        if body.schedule is not None:
            room["schedule"] = body.schedule.model_dump()
        store.save_rooms()
        return ok(None, "updated")

    @_api
    def DELETE(self, room_id):
        store = st.get()
        if room_id not in store.rooms:
            return err(f"Room {room_id} not found", code=404)
        del store.rooms[room_id]
        store.save_rooms()
        return ok(None, "deleted")


class Policies(Resource):
    @_api
    def GET(self, room_id=None):                       # ?room_id=xxx
        store = st.get()
        if room_id and room_id not in store.rooms:
            return err(f"Room {room_id} not found", code=404)
        result = list(store.policies.values())
        if room_id:
            result = [p for p in result if p.get("room_id") == room_id]
        return ok(result)

    @_api
    def POST(self):
        body = PolicyCreateDTO.model_validate(_request_body())
        store = st.get()
        if body.policy_id in store.policies:
            return err(f"Policy {body.policy_id} already exists", code=409)
        if body.room_id and body.room_id not in store.rooms:
            return err(f"Room {body.room_id} not found", code=404)

        error = verify_device_class(body.metric) or verify_device({body.target_device})
        if error:
            return error

        store.policies[body.policy_id] = body.model_dump()
        store.save_policies()
        return ok(None, "created")

    @_api
    def PUT(self, policy_id):
        body = PolicyUpdateDTO.model_validate(_request_body())
        store = st.get()
        policy = store.policies.get(policy_id)
        if policy is None:
            return err(f"Policy {policy_id} not found", code=404)
        if body.room_id and body.room_id not in store.rooms:
            return err(f"Room {body.room_id} not found", code=404)

        error = None
        if body.target_device:
            error = verify_device({body.target_device})
        if not error and body.metric:
            error = verify_device_class(body.metric)
        if error:
            return error

        for field, val in body.model_dump(exclude_none=True).items():
            policy[field] = val
        store.save_policies()
        return ok(None, "updated")

    @_api
    def DELETE(self, policy_id):
        store = st.get()
        if policy_id not in store.policies:
            return err(f"Policy {policy_id} not found", code=404)
        del store.policies[policy_id]
        store.save_policies()
        return ok(None, "deleted")


class Conflicts(Resource):
    @_api
    def GET(self, room_id=None):
        store = st.get()
        if room_id and room_id not in store.rooms:
            return err(f"Room {room_id} not found", code=404)
        result = list(store.conflicts.values())
        if room_id:
            result = [c for c in result if c.get("room_id") == room_id]
        return ok(result)

    @_api
    def POST(self):
        body = ConflictCreateDTO.model_validate(_request_body())
        store = st.get()
        if body.conflict_id in store.conflicts:
            return err(f"Conflict rule {body.conflict_id} already exists", code=409)
        if body.room_id and body.room_id not in store.rooms:
            return err(f"Room {body.room_id} not found", code=404)

        error = verify_device(body.devices) or verify_strategy(body.strategy)
        if error:
            return error

        store.conflicts[body.conflict_id] = body.model_dump()
        store.save_conflicts()
        return ok(None, "created")

    @_api
    def PUT(self, conflict_id):
        body = ConflictUpdateDTO.model_validate(_request_body())
        store = st.get()
        conflict = store.conflicts.get(conflict_id)
        if conflict is None:
            return err(f"Conflict rule {conflict_id} not found", code=404)
        if body.room_id and body.room_id not in store.rooms:
            return err(f"Room {body.room_id} not found", code=404)

        error = None
        if body.devices:
            error = verify_device(body.devices)
        if not error and body.strategy:
            error = verify_strategy(body.strategy)
        if error:
            return error

        for field, val in body.model_dump(exclude_none=True).items():
            conflict[field] = val
        store.save_conflicts()
        return ok(None, "updated")

    @_api
    def DELETE(self, conflict_id):
        store = st.get()
        if conflict_id not in store.conflicts:
            return err(f"Conflict rule {conflict_id} not found", code=404)
        del store.conflicts[conflict_id]
        store.save_conflicts()
        return ok(None, "deleted")


class Services(Resource):
    @_api
    def GET(self):
        store = st.get()
        return ok(list(store.services.values()))

    @_api
    def POST(self, action=None):                       # POST /services/register
        if action != "register":
            raise cherrypy.NotFound()
        body = ServiceRegisterDTO.model_validate(_request_body())
        store = st.get()
        svc = body.model_dump()
        svc["status"] = "unknown"
        svc["last_seen"] = 0
        store.services[body.service_id] = svc
        store.save_services()
        return ok(None, "registered")

    @_api
    def DELETE(self, service_id):
        store = st.get()
        if service_id not in store.services:
            return err(f"Service {service_id} not found", code=404)
        del store.services[service_id]
        store.save_services()
        return ok(None, "deleted")


class RoomAggregate(Resource):
    @_api
    def GET(self, room_id):                            # GET /room/{id}
        store = st.get()
        room = store.rooms.get(room_id)
        if room is None:
            return err(f"Room {room_id} not found", code=404)

        # Resolve devices
        sensors, actuators = [], []
        for dev_id in room.get("device_ids", []):
            dev = store.devices.get(dev_id)
            if dev is None:
                continue
            dto = _device_to_dto(dev)
            if dev.get("category") == "sensor":
                sensors.append(dto)
            else:
                actuators.append(dto)

        # Load room-scoped policies and conflicts
        policies = [p for p in store.policies.values() if p.get("room_id") == room_id]
        conflicts = [c for c in store.conflicts.values() if c.get("room_id") == room_id]

        return ok({
            "room_id": room_id,
            "sensors": sensors,
            "actuators": actuators,
            "policies": policies,
            "conflicts": conflicts,
            "energy_mode": room.get("energy_mode", "NORMAL"),
            "schedule": room.get("schedule", {}),
        })


def build_app():
    """Return (root, conf) for cherrypy.quickstart(root, "/", conf)."""
    root = Root()
    root.docs = Docs()
    root.health = Health()
    root.devices = Devices()
    root.rooms = Rooms()
    root.policies = Policies()
    root.conflicts = Conflicts()
    root.services = Services()
    root.room = RoomAggregate()
    conf = {"/": {
        "request.dispatch": cherrypy.dispatch.MethodDispatcher(),
        "error_page.default": _json_error_page,
    }}
    return root, conf