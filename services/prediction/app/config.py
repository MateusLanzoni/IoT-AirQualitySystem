from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    port: int = 8003
    model_path: str = "/app/model/model.joblib"
    default_horizon_minutes: int = 15
    default_lookback_points: int = 12
    history_point_interval_seconds: int = 300

    service_name: str = "prediction-service"
    service_version: str = "0.2.0"
    service_type: str = "prediction"
    service_host: str = "prediction-service"
    service_url: str = "http://prediction-service:8003"

    room_catalog_base_url: str = "http://catalog-service:8001"
    room_catalog_register_path: str = "/services/register"
    room_catalog_heartbeat_path: str = "/services/{service_id}/heartbeat"
    room_catalog_heartbeat_enabled: bool = False

    thingspeak_adapter_base_url: str = "http://adaptor-service:8000"
    thingspeak_adapter_history_path: str = "/api/v1/history"
    thingspeak_room_param: str = "roomid"
    thingspeak_start_param: str = "starttime"
    thingspeak_end_param: str = "endtime"

    outdoor_aqi_base_url: str = "https://api.waqi.info"
    outdoor_aqi_path: str = "/feed"
    outdoor_aqi_token: str | None = None
    outdoor_aqi_city: str = "@13202"
    outdoor_aqi_source_name: str = "waqi-turin"

    request_timeout_seconds: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )


settings = Settings()
