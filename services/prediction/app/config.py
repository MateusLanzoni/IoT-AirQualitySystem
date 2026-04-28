from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    port: int = 8002
    model_path: str = "services/prediction/model/model.joblib"
    default_horizon_minutes: int = 15
    default_lookback_points: int = 12

    service_name: str = "prediction-service"
    service_version: str = "0.2.0"
    service_host: str = "prediction"
    service_url: str = "http://prediction:8002"

    room_catalog_base_url: str = "http://room-catalog:8000"
    room_catalog_register_path: str = "/services/register"
    room_catalog_heartbeat_path: str = "/services/{service_id}/heartbeat"
    room_catalog_heartbeat_enabled: bool = False

    thingspeak_adapter_base_url: str = "http://thingspeak-adapter:8004"
    thingspeak_adapter_history_path: str = "/prediction/history"

    outdoor_aqi_base_url: str = "https://api.waqi.info"
    outdoor_aqi_path: str = "/feed"
    outdoor_aqi_token: str | None = None
    outdoor_aqi_city: str = "turin"
    outdoor_aqi_source_name: str = "waqi-turin"

    request_timeout_seconds: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )


settings = Settings()
