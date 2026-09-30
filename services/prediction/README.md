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
Forecasting, risk classification, training and the Pydantic schemas are unchanged.

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
| `MODEL_PATH` | `/app/model/model.joblib` |
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

## Training

```bash
python3 services/prediction/train.py --csv-path /path/to/data.csv
```

```bash
python3 services/prediction/train.py --zip-path /path/to/archive.zip
```

The trained model is written to:

```text
services/prediction/model/model.joblib
```

Model artifacts are ignored by git. Without a trained model, the service uses a heuristic baseline.

## Tests

After installing `requirements.txt`, run from `services/prediction`:

```bash
python -m unittest discover -s tests -v
```

Tests launch a real CherryPy process on a temporary port and use local HTTP
fixtures for Catalog, Adaptor and WAQI. They cover the four endpoint contracts,
validation, registration/heartbeat, missing data, dependency failures, concurrent
requests, model loading and graceful shutdown. The model fixture tests inference
plumbing, not the Random Forest's predictive accuracy. Live credentials are not needed.

## Presentation Update

In the supplied presentation, change slide 24's Prediction framework label to
`CherryPy - ML forecaster + baseline`, and slide 26 to `Exposed via CherryPy`.
For the demo, use curl or Postman instead of the old `/docs` page. Explain that
Prediction uses threaded synchronous REST handling; the other services' MQTT
architecture is separate from this migration.
