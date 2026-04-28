from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ConfigDict


class IndoorSnapshot(BaseModel):
    temperature: float = Field(..., description="Indoor temperature in Celsius.")
    humidity: float = Field(..., ge=0, le=100, description="Indoor relative humidity percentage.")
    co2: float = Field(..., ge=0, description="CO2 concentration in ppm.")
    pm25: float = Field(..., ge=0, description="PM2.5 concentration in ug/m3.")


class OutdoorSnapshot(BaseModel):
    aqi: float | None = Field(default=None, ge=0, description="Outdoor AQI value.")
    source: str | None = None
    fetched_at: datetime | None = None


class HistoryPoint(IndoorSnapshot):
    timestamp: datetime
    room_id: str | None = None
    device_id: str | None = None
    source: str | None = None


class PredictionRequest(BaseModel):
    room_id: str
    horizon_minutes: int = Field(default=15, ge=1, le=180)
    lookback_points: int | None = Field(default=None, ge=3, le=288)
    timestamp: datetime | None = None
    outdoor_aqi_override: float | None = Field(default=None, ge=0)


class ForecastValues(BaseModel):
    temperature: float
    humidity: float
    co2: float
    pm25: float


class PredictionResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    room_id: str
    generated_at: datetime
    horizon_minutes: int
    model_source: str
    indoor_latest: IndoorSnapshot
    outdoor: OutdoorSnapshot
    history_points_used: int
    prediction: ForecastValues
    risk: str
    summary: str


class ServiceRegistrationPayload(BaseModel):
    service_id: str
    name: str
    version: str
    base_url: str
    endpoints: list[str]
    capabilities: list[str]
    status: str = "online"


class HistoryResponse(BaseModel):
    room_id: str
    points: list[HistoryPoint]
    latest: IndoorSnapshot | None = None
    raw: dict[str, Any] | None = None
