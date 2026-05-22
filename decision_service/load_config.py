
import yaml
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Allow container-level overrides via environment variables
    if os.getenv("SERVER_HOST"):
        cfg["server"]["host"] = os.getenv("SERVER_HOST")
    if os.getenv("MQTT_BROKER"):
        cfg["mqtt"]["broker"] = os.getenv("MQTT_BROKER")
    if os.getenv("CATALOG_BASE_URL"):
        cfg["services"]["catalog_base_url"] = os.getenv("CATALOG_BASE_URL")
    if os.getenv("PREDICTION_BASE_URL"):
        cfg["services"]["prediction_base_url"] = os.getenv("PREDICTION_BASE_URL")
    return cfg