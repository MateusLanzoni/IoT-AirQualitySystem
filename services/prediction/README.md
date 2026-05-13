# Prediction Service

FastAPI service for AirGuard indoor air quality forecasting.

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
uvicorn app.main:app --host 0.0.0.0 --port 8003
```

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
