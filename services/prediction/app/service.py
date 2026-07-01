from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from .clients import ClientBundle
from .config import settings
from .forecasting import load_forecaster
from .risk import classify_risk
from .schemas import PredictionRequest, PredictionResponse, ServiceRegistrationPayload


class PredictionService:
    def __init__(self, clients: ClientBundle):
        self.clients = clients
        self.forecaster = load_forecaster(settings.model_path)
        self.registration_state = "not-started"

    async def register(self) -> None:
        payload = ServiceRegistrationPayload(
            service_id=settings.service_name,
            service_name=settings.service_name,
            type=settings.service_type,
            endpoint=settings.service_url,
            health_endpoint="/health",
        )
        try:
            await self.clients.room_catalog.register_service(payload)
            self.registration_state = "registered"
            if settings.room_catalog_heartbeat_enabled:
                await self.clients.room_catalog.heartbeat(settings.service_name)
        except Exception:
            self.registration_state = "failed"

    async def predict(self, request: PredictionRequest) -> PredictionResponse:
        lookback_points = request.lookback_points or settings.default_lookback_points

        history_response = await self.clients.thingspeak.fetch_history(
            room_id=request.room_id,
            lookback_points=lookback_points,
            end_time=request.timestamp,
        )
        if not history_response.points:
            raise HTTPException(status_code=404, detail=f"No historical data available for room '{request.room_id}'")

        latest = history_response.latest
        if latest is None:
            raise HTTPException(status_code=500, detail="Unable to derive the latest indoor snapshot from history")

        outdoor = await self.clients.outdoor_aqi.fetch_current(request.outdoor_aqi_override)
        forecast = self.forecaster.predict_from_series(
            history=history_response.points,
            indoor_latest=latest,
            outdoor_aqi=outdoor.aqi,
            horizon_minutes=request.horizon_minutes,
            timestamp=request.timestamp or datetime.now(timezone.utc),
        )
        risk, summary = classify_risk(forecast)

        return PredictionResponse(
            room_id=request.room_id,
            generated_at=datetime.now(timezone.utc),
            horizon_minutes=request.horizon_minutes,
            model_source=getattr(self.forecaster, "source", "unknown"),
            indoor_latest=latest,
            outdoor=outdoor,
            history_points_used=len(history_response.points),
            prediction=forecast,
            risk=risk,
            summary=summary,
        )

    @staticmethod
    def to_decision_payload(response: PredictionResponse) -> dict:
        values = response.prediction.model_dump()
        predictions = {
            metric: {
                "value": value,
                "horizon_minutes": response.horizon_minutes,
                "generated_at": response.generated_at.isoformat(),
            }
            for metric, value in values.items()
        }
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "room_id": response.room_id,
                "predictions": predictions,
                "risk": response.risk,
                "summary": response.summary,
            },
        }
