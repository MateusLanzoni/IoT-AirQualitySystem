"""CherryPy HTTP interface. Run ``python -m app.main`` from services/prediction."""

import json

import cherrypy
import httpx
from pydantic import ValidationError

from .clients import ClientBundle, OutdoorAqiClient, RoomCatalogClient, ThingSpeakAdapterClient
from .config import settings
from .schemas import PredictionRequest
from .service import PredictionService, PredictionServiceError


def build_service() -> PredictionService:
    return PredictionService(
        ClientBundle(
            room_catalog=RoomCatalogClient(
                base_url=settings.room_catalog_base_url,
                register_path=settings.room_catalog_register_path,
                heartbeat_path=settings.room_catalog_heartbeat_path,
                timeout=settings.request_timeout_seconds,
            ),
            thingspeak=ThingSpeakAdapterClient(
                base_url=settings.thingspeak_adapter_base_url,
                history_path=settings.thingspeak_adapter_history_path,
                room_param=settings.thingspeak_room_param,
                start_param=settings.thingspeak_start_param,
                end_param=settings.thingspeak_end_param,
                point_interval_seconds=settings.history_point_interval_seconds,
                lookback_days=settings.history_lookback_days,
                timeout=settings.request_timeout_seconds,
            ),
            outdoor_aqi=OutdoorAqiClient(
                base_url=settings.outdoor_aqi_base_url,
                path=settings.outdoor_aqi_path,
                token=settings.outdoor_aqi_token,
                city=settings.outdoor_aqi_city,
                source_name=settings.outdoor_aqi_source_name,
                timeout=settings.request_timeout_seconds,
            ),
        )
    )


def json_error_page(status, message, traceback, version):
    """Keep HTTP errors machine-readable without exposing internal tracebacks."""
    cherrypy.response.headers["Content-Type"] = "application/json"
    detail = "Internal Server Error" if str(status).startswith("500") else message
    return json.dumps({"detail": detail})


def validate_request(payload, location: str) -> PredictionRequest:
    try:
        return PredictionRequest.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False)
        for error in errors:
            error["loc"] = [location, *error["loc"]]
        # Supply the validation body through a dedicated 422 error page.
        raise cherrypy.HTTPError(422, json.dumps(errors)) from exc


def validation_error_page(status, message, traceback, version):
    cherrypy.response.headers["Content-Type"] = "application/json"
    return json.dumps({"detail": json.loads(message)})


def call_dependency(function, *args):
    """Translate service/dependency errors at the web boundary."""
    try:
        return function(*args)
    except PredictionServiceError as exc:
        raise cherrypy.HTTPError(exc.status_code, exc.detail) from exc
    except httpx.TimeoutException as exc:
        raise cherrypy.HTTPError(504, "Upstream service timed out") from exc
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        # HTTPX messages can contain API tokens in request URLs.
        raise cherrypy.HTTPError(502, "Upstream service request failed") from exc


class DecisionPredictionEndpoint:
    def __init__(self, service: PredictionService):
        self.service = service

    @cherrypy.expose
    @cherrypy.tools.allow(methods=["GET"])
    @cherrypy.tools.json_out()
    def default(self, *path, **query):
        if len(path) != 1:
            raise cherrypy.HTTPError(404, "Not Found")
        request = validate_request(
            {
                "room_id": path[0],
                "horizon_minutes": query.get("horizon_minutes", settings.default_horizon_minutes),
                "lookback_points": query.get("lookback_points", settings.default_lookback_points),
            },
            "query",
        )
        response = call_dependency(self.service.predict, request)
        return self.service.to_decision_payload(response)


class PredictionAPI:
    def __init__(self, service: PredictionService):
        self.service = service
        self.prediction = DecisionPredictionEndpoint(service)
        # Preserve the existing hyphenated endpoint without a routing dependency.
        setattr(self, "outdoor-aqi", self.outdoor_aqi)

    @cherrypy.expose
    @cherrypy.tools.allow(methods=["GET"])
    @cherrypy.tools.json_out()
    def health(self, **unused_query):
        return {
            "status": "ok",
            "service": "prediction",
            "model_source": getattr(self.service.forecaster, "source", "unknown"),
            "default_horizon_minutes": settings.default_horizon_minutes,
            "default_lookback_points": settings.default_lookback_points,
            "room_catalog_registration": self.service.registration_state,
            "dependencies": {
                "room_catalog": settings.room_catalog_base_url,
                "thingspeak_adapter": settings.thingspeak_adapter_base_url,
                "outdoor_aqi": settings.outdoor_aqi_base_url,
            },
        }

    @cherrypy.expose
    @cherrypy.tools.allow(methods=["POST"])
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def predict(self, **unused_query):
        request = validate_request(cherrypy.request.json, "body")
        return call_dependency(self.service.predict, request).model_dump(mode="json")

    @cherrypy.tools.allow(methods=["GET"])
    @cherrypy.tools.json_out()
    def outdoor_aqi(self, **unused_query):
        return call_dependency(self.service.clients.outdoor_aqi.fetch_current).model_dump(mode="json")

    outdoor_aqi.exposed = True


def create_app(service: PredictionService | None = None) -> cherrypy.Application:
    return cherrypy.Application(
        PredictionAPI(service if service is not None else build_service()),
        script_name="",
        config={
            "/": {
                "error_page.default": json_error_page,
                "error_page.422": validation_error_page,
                "request.show_tracebacks": False,
            }
        },
    )


def main():
    application = create_app()
    cherrypy.config.update(
        {
            "environment": "production",
            "server.socket_host": "0.0.0.0",
            "server.socket_port": settings.port,
            "engine.autoreload.on": False,
        }
    )
    cherrypy.engine.subscribe("start", application.root.service.register)
    # quickstart also installs signal handling for graceful Docker shutdown.
    cherrypy.quickstart(application)


if __name__ == "__main__":
    main()
