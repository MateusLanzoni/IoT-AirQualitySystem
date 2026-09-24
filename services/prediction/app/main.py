from contextlib import asynccontextmanager

from fastapi import FastAPI, Query

from .clients import ClientBundle, OutdoorAqiClient, RoomCatalogClient, ThingSpeakAdapterClient
from .config import settings
from .schemas import PredictionRequest
from .service import PredictionService


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = PredictionService(
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
    await app.state.service.register()
    yield


app = FastAPI(
    title="AirGuard Prediction Service",
    version=settings.service_version,
    description="Short-term indoor air quality forecasting service for AirGuard.",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    service = app.state.service
    return {
        "status": "ok",
        "service": "prediction",
        "model_source": getattr(service.forecaster, "source", "unknown"),
        "default_horizon_minutes": settings.default_horizon_minutes,
        "default_lookback_points": settings.default_lookback_points,
        "room_catalog_registration": service.registration_state,
        "dependencies": {
            "room_catalog": settings.room_catalog_base_url,
            "thingspeak_adapter": settings.thingspeak_adapter_base_url,
            "outdoor_aqi": settings.outdoor_aqi_base_url,
        },
    }


@app.post("/predict")
async def predict(request: PredictionRequest):
    return await app.state.service.predict(request)


@app.get("/outdoor-aqi")
async def outdoor_aqi():
    return await app.state.service.clients.outdoor_aqi.fetch_current()


@app.get("/prediction/{room_id}")
async def prediction_for_decision(
    room_id: str,
    horizon_minutes: int = Query(default=settings.default_horizon_minutes, ge=1, le=180),
    lookback_points: int = Query(default=settings.default_lookback_points, ge=3, le=288),
):
    request = PredictionRequest(
        room_id=room_id,
        horizon_minutes=horizon_minutes,
        lookback_points=lookback_points,
    )
    response = await app.state.service.predict(request)
    return app.state.service.to_decision_payload(response)
