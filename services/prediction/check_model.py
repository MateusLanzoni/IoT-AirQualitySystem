"""Inspect your configured artifact. Exit 0 only for a validated Random Forest."""
import json
from app.config import settings
from app.forecasting import load_forecaster


def main():
    forecaster = load_forecaster(settings.model_path)
    print(json.dumps({"model_source": forecaster.source, **forecaster.diagnostics}, indent=2))
    return 0 if forecaster.source == "trained-model" else 1


if __name__ == "__main__":
    raise SystemExit(main())
