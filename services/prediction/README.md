# Prediction Service

CherryPy service for AirGuard indoor air quality forecasting.

## Purpose

The service gives the Decision Service short-term forecasts for:

- temperature
- humidity
- CO2
- PM2.5

It fetches indoor history from the ThingSpeak Adapter and outdoor AQI for Torino from WAQI station `@13202`.

## Run Locally

```bash
cd services/prediction
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

OUTDOOR_AQI_TOKEN="your-token-here" \
ROOM_CATALOG_BASE_URL="http://localhost:8001" \
THINGSPEAK_ADAPTER_BASE_URL="http://localhost:8000" \
python -m app.main
```

CherryPy listens on `0.0.0.0` using `PORT` (default `8003`). Requests and
downstream HTTPX calls are synchronous and handled by CherryPy worker threads.
Risk classification remains compatible. Training and model inference share a corrected feature pipeline.

## Run with Docker Compose

From the repository root:

```bash
docker compose up -d --build prediction-service
curl http://localhost:8003/health
curl "http://localhost:8003/prediction/room1"
```

The existing Compose service name, port, dependency URLs and environment variables
remain compatible. Other services do not need framework changes to call Prediction.

## Endpoints

### `GET /health`

```bash
curl http://localhost:8003/health
```

### `GET /prediction/{room_id}`

Main Decision Service endpoint.

```bash
curl "http://localhost:8003/prediction/room1"
```

Returns:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "room_id": "room1",
    "predictions": {
      "temperature": {
        "value": 25.5,
        "horizon_minutes": 15,
        "generated_at": "2026-05-13T10:00:00Z"
      }
    },
    "risk": "normal",
    "summary": "Forecast remains within the expected comfort and air quality range."
  }
}
```

### `GET /outdoor-aqi`

Torino AQI gateway endpoint.

```bash
curl http://localhost:8003/outdoor-aqi
```

### `POST /predict`

Manual/debug endpoint.

```bash
curl -X POST http://localhost:8003/predict \
  -H "Content-Type: application/json" \
  -d '{"room_id":"room1","horizon_minutes":15,"lookback_points":12}'
```

CherryPy does not generate Swagger/OpenAPI automatically, so `/docs` is no longer
available. Use the examples above or Postman for the presentation demo.

## Validation and Errors

Pydantic still validates requests. `horizon_minutes` must be `1`–`180` and
`lookback_points`, when supplied, must be `3`–`288`. Invalid body/query values
return HTTP `422` with a JSON `detail` list. Malformed JSON returns `400`;
unsupported body content types return `415`; unsupported methods return `405`.

No indoor history returns `404` with a JSON `detail` message. Upstream HTTP/network
failures return `502`, and upstream timeouts return `504`. Unexpected errors return
a generic JSON `500` without tracebacks or dependency URLs in the response.

Without a WAQI token, forecasting continues with `aqi: null` and
`source: "unconfigured"`. A configured WAQI outage still fails that forecast
request; this migration does not add caching, retries or an outage fallback.

## Environment Variables

| Variable | Default |
| --- | --- |
| `PORT` | `8003` |
| `MODEL_PATH` | `<prediction-service-directory>/model/model.joblib` (`/app/model/model.joblib` in Docker) |
| `ROOM_CATALOG_BASE_URL` | `http://catalog-service:8001` |
| `THINGSPEAK_ADAPTER_BASE_URL` | `http://adaptor-service:8000` |
| `THINGSPEAK_ADAPTER_HISTORY_PATH` | `/api/v1/history` |
| `OUTDOOR_AQI_BASE_URL` | `https://api.waqi.info` |
| `OUTDOOR_AQI_CITY` | `@13202` |
| `OUTDOOR_AQI_TOKEN` | empty |

The Torino feed is:

```text
https://api.waqi.info/feed/@13202/?token=$OUTDOOR_AQI_TOKEN
```

Keep the token in the runtime environment, not in source control.

## ThingSpeak Adapter Contract

Expected endpoint:

```text
GET /api/v1/history?roomid=<room_id>&starttime=<iso>&endtime=<iso>
```

Field mapping:

| Field | Metric |
| --- | --- |
| `field2` | temperature |
| `field3` | humidity |
| `field4` | CO2 |
| `field5` | PM2.5 |

## Catalog Registration

The service registers on startup:

```text
POST /services/register
```

Payload:

```json
{
  "service_id": "prediction-service",
  "service_name": "prediction-service",
  "type": "prediction",
  "endpoint": "http://prediction-service:8003",
  "health_endpoint": "/health"
}
```

## Train and Verify Random Forest

A fresh checkout contains no trained model. Until you train and restart Prediction,
`heuristic-baseline` is the expected mode. A successful HTTP response alone does
not prove Random Forest inference.

The most direct route uses the room history already available through your Adaptor.
From the repository root, with your existing environment configuration:

```bash
docker compose up -d --build prediction-service
docker compose exec prediction-service python train.py --room-id room1 --horizon-minutes 15
# Save the artifact and evaluation before any future container rebuild.
docker cp airguard-prediction:/app/model/model.joblib services/prediction/model/model.joblib
docker cp airguard-prediction:/app/model/model.metrics.json services/prediction/model/model.metrics.json
docker compose restart prediction-service
docker compose exec prediction-service python check_model.py
curl http://localhost:8003/health
curl "http://localhost:8003/prediction/room1?horizon_minutes=15"
```

Stop if training fails; do not proceed as though a model was created. Training
needs at least 30 usable samples after five-minute aggregation, lags and targets,
plus sufficient samples for the purged evaluation split. The room-history command
uses the configured Adaptor URL and history window. It does not need a WAQI token.

If `MODEL_PATH` is overridden, use that container path in the copy commands.
The default local path now also works when running outside Docker.

To train from your own CSV or a ZIP containing exactly one CSV, from
`services/prediction` with the pinned requirements installed:

```bash
python train.py --csv-path /absolute/path/to/room-data.csv --horizon-minutes 15
# Or: python train.py --zip-path /absolute/path/to/room-data.zip
python check_model.py
```

Train with the same scikit-learn version as the service. Model files and evaluation
reports are ignored by Git; no synthetic demo model is packaged.

### Evidence that your model exists and works

`check_model.py` exits zero only after the file is loaded, verified as four fitted
Random Forest regressors, checked against the shared input schema and runtime
version, and exercised with an inference self-test. It checks the file on disk;
restart Prediction to load a newly trained file into the running server.

In `/health`, look for:

```json
{
  "model_source": "trained-model",
  "model": {
    "loaded": true,
    "self_test": "passed",
    "fallback_reason": null,
    "model_type": "MultiOutputRegressor[RandomForestRegressor]"
  }
}
```

This is an excerpt. Next call `/prediction/room1?horizon_minutes=15`: its
`data.model_source` must also be `trained-model`. `/predict` reports the same
information at the top level. `/health` then reports the last successful
inference's model source. These checks distinguish loading from real room inference.

If a request uses baseline, inspect `model_diagnostics.fallback_reason` (inside
`data` for the Decision endpoint). Missing/corrupt/legacy artifacts, incompatible
versions, insufficient recent history and unsupported horizons are visible.
A loaded model remains available while an individual unsupported request uses
baseline; therefore check the response source, not just `/health`.

### What was repaired

- ThingSpeak CSV mapping is `field4` CO2 and `field5` PM2.5, matching runtime.
- Training/inference use identical 32 feature names and order.
- Both aggregate in five-minute UTC bins; lags use distinct history bins.
- Rolling statistics use three bins and population standard deviation in both paths.
- Missing features only forward-fill up to three bins; future data never fills inputs.
- Sparse sensor rows are retained, and four available metrics form the latest snapshot.
- New versioned artifacts reject old models trained under the broken contract.
- Chronological 80/20 evaluation purges training labels that reach the test period.
  Per-metric MAE/RMSE and a persistence comparison are saved in `model.metrics.json`.
  The deployable forest is then refitted on all usable samples.

### Limits relevant to your presentation

The model is trained for one horizon (15 minutes by default). Other horizons use
baseline with an explicit `unsupported_horizon` reason. The CSV pipeline has no
historical AQI labels: RF uses the indoor features with AQI fixed at zero; it does
not claim learned outdoor enrichment. The baseline still uses AQI when available.

Forecasts are anchored to the newest history bin, shown by
`model_diagnostics.forecast_reference_at`. Old history produces an old reference;
do not present it as a forecast of current room conditions.

MAE/RMSE measure this dataset's held-out performance; there is no universal accuracy
percentage. Compare with persistence before claiming an improvement. Tests use
synthetic fixtures to verify software execution, not real-world predictive accuracy.

## Tests

After installing `requirements.txt`, run from `services/prediction`:

```bash
python -m unittest discover -s tests -v
```

Tests launch a real CherryPy process on a temporary port and use local HTTP
fixtures for Catalog, Adaptor and WAQI. They cover the four endpoint contracts,
validation, registration/heartbeat, missing data, dependency failures, concurrent
requests, model loading and graceful shutdown. The model fixtures train actual Random Forests and test inference
plumbing, not real-world predictive accuracy. Live credentials are not needed.

## Presentation Update

In the supplied presentation, change slide 24's Prediction framework label to
`CherryPy - ML forecaster + baseline`, and slide 26 to `Exposed via CherryPy`.
For the demo, use curl or Postman instead of the old `/docs` page. Explain that
Prediction uses threaded synchronous REST handling; the other services' MQTT
architecture is separate from this migration.
