from __future__ import annotations

from datetime import datetime, timezone
import logging

from .clients import ClientBundle
from .config import settings
from .forecasting import BaselineForecaster, ModelInferenceUnavailable, load_forecaster
from .risk import classify_risk
from .schemas import PredictionRequest, PredictionResponse, ServiceRegistrationPayload


class PredictionServiceError(Exception):
    """An expected forecast failure, independent of the HTTP framework."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class PredictionService:
    def __init__(self, clients: ClientBundle):
        self.clients = clients
        self.forecaster = load_forecaster(settings.model_path)
        self.registration_state = "not-started"
        self.last_inference = {"status": "not-run"}

    def register(self) -> None:
        payload = ServiceRegistrationPayload(
            service_id=settings.service_name,
            service_name=settings.service_name,
            type=settings.service_type,
            endpoint=settings.service_url,
            health_endpoint="/health",
        )
        try:
            self.clients.room_catalog.register_service(payload)
            self.registration_state = "registered"
            if settings.room_catalog_heartbeat_enabled:
                self.clients.room_catalog.heartbeat(settings.service_name)
        except Exception:
            self.registration_state = "failed"

    def predict(self, request: PredictionRequest) -> PredictionResponse:
        lookback_points = request.lookback_points or settings.default_lookback_points

        history_response = self.clients.thingspeak.fetch_history(
            room_id=request.room_id,
            lookback_points=lookback_points,
            end_time=request.timestamp,
        )
        if not history_response.points:
            raise PredictionServiceError(status_code=404, detail=f"No historical data available for room '{request.room_id}'")

        latest = history_response.latest
        if latest is None:
            raise PredictionServiceError(status_code=404, detail="History does not contain all four indoor metrics")

        outdoor = self.clients.outdoor_aqi.fetch_current(request.outdoor_aqi_override)
        arguments = dict(history=history_response.points, indoor_latest=latest,
                         outdoor_aqi=outdoor.aqi, horizon_minutes=request.horizon_minutes,
                         timestamp=request.timestamp or datetime.now(timezone.utc))
        active_forecaster = self.forecaster
        diagnostics = dict(self.forecaster.diagnostics)
        try:
            forecast = active_forecaster.predict_from_series(**arguments)
        except ModelInferenceUnavailable as exc:
            active_forecaster = BaselineForecaster()
            diagnostics["fallback_reason"] = str(exc)
            logging.getLogger(__name__).warning("Request using baseline: %s", exc)
            forecast = active_forecaster.predict_from_series(**arguments)
        diagnostics["inference_model_source"] = active_forecaster.source
        reference = max(point.timestamp for point in history_response.points).astimezone(timezone.utc)
        if active_forecaster.source == "trained-model":
            reference = reference.replace(minute=reference.minute // 5 * 5, second=0, microsecond=0)
        diagnostics["forecast_reference_at"] = reference.isoformat()
        self.last_inference = {"status": "succeeded", "model_source": active_forecaster.source,
                               "fallback_reason": diagnostics.get("fallback_reason"),
                               "room_id": request.room_id}
        risk, summary = classify_risk(forecast)

        return PredictionResponse(
            room_id=request.room_id,
            generated_at=datetime.now(timezone.utc),
            horizon_minutes=request.horizon_minutes,
            model_source=active_forecaster.source,
            indoor_latest=latest,
            outdoor=outdoor,
            history_points_used=len(history_response.points),
            prediction=forecast,
            risk=risk,
            summary=summary,
            model_diagnostics=diagnostics,
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
                "model_source": response.model_source,
                "model_diagnostics": response.model_diagnostics,
            },
        }
