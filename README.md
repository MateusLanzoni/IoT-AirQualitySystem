# AirGuard Prediction Service

This branch contains the Prediction Service for the AirGuard IoT Air Quality System. The service provides short-term indoor air quality forecasts to the Decision Service by combining recent indoor telemetry from the ThingSpeak Adapter with outdoor AQI data for Torino, Italy.

## What This Branch Contains

- `services/prediction/app/`: FastAPI application code
- `services/prediction/train.py`: model training entrypoint
- `services/prediction/Dockerfile`: container build definition
- `services/prediction/requirements.txt`: Python dependencies
- `services/prediction/docs/api-contract.md`: integration contract for other services
- `docker-compose.yml`: Prediction Service deployment configuration

The service is REST-based. It does not publish MQTT commands and does not decide actuator actions. Those responsibilities remain with the Decision Service.

## Service Responsibilities

- Register itself in the Catalog Service at startup
- Fetch historical room telemetry from the ThingSpeak Adapter
- Fetch outdoor AQI for Torino from the WAQI feed
- Generate forecasts for temperature, humidity, CO2, and PM2.5
- Return prediction data in the format expected by the Decision Service
- Expose a small Outdoor AQI gateway endpoint for debugging and integration checks

## Architecture Flow

```text
Decision Service
  -> GET /prediction/{room_id}
Prediction Service
  -> GET /api/v1/history from ThingSpeak Adapter
  -> GET /feed/@13202 from WAQI
Prediction Service
  -> returns forecast to Decision Service
Decision Service
  -> evaluates policies and publishes MQTT commands
```

## Runtime Configuration

The service uses environment variables through `pydantic-settings`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8003` | Prediction Service port |
| `MODEL_PATH` | `/app/model/model.joblib` | Trained model path inside container |
| `ROOM_CATALOG_BASE_URL` | `http://catalog-service:8001` | Catalog Service base URL |
| `THINGSPEAK_ADAPTER_BASE_URL` | `http://adaptor-service:8000` | ThingSpeak Adapter base URL |
| `THINGSPEAK_ADAPTER_HISTORY_PATH` | `/api/v1/history` | History endpoint path |
| `OUTDOOR_AQI_BASE_URL` | `https://api.waqi.info` | WAQI base URL |
| `OUTDOOR_AQI_CITY` | `@13202` | Torino WAQI station identifier |
| `OUTDOOR_AQI_TOKEN` | empty | WAQI API token |

Do not commit the real WAQI token. Set it locally or in deployment:

```bash
export OUTDOOR_AQI_TOKEN="your-token-here"
```

The Torino WAQI feed format is:

```text
https://api.waqi.info/feed/@13202/?token=$OUTDOOR_AQI_TOKEN
```

## API Endpoints

### `GET /health`

Returns service status, model source, dependency URLs, and Catalog registration state.

```bash
curl http://localhost:8003/health
```

### `GET /prediction/{room_id}`

Main endpoint used by the Decision Service.

```bash
curl "http://localhost:8003/prediction/room1"
```

Response format:

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
      },
      "humidity": {
        "value": 50.2,
        "horizon_minutes": 15,
        "generated_at": "2026-05-13T10:00:00Z"
      },
      "co2": {
        "value": 720.0,
        "horizon_minutes": 15,
        "generated_at": "2026-05-13T10:00:00Z"
      },
      "pm25": {
        "value": 18.0,
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

Returns the current configured outdoor AQI reading for Torino.

```bash
curl http://localhost:8003/outdoor-aqi
```

### `POST /predict`

Manual/debug endpoint. The Decision Service should use `GET /prediction/{room_id}`.

```bash
curl -X POST http://localhost:8003/predict \
  -H "Content-Type: application/json" \
  -d '{"room_id":"room1","horizon_minutes":15,"lookback_points":12}'
```

## ThingSpeak Adapter Integration

The Prediction Service expects the adapter endpoint implemented in the sensor branch:

```text
GET /api/v1/history?roomid=<room_id>&starttime=<iso>&endtime=<iso>
```

Expected field mapping:

| Field | Meaning |
| --- | --- |
| `field2` | temperature |
| `field3` | humidity |
| `field4` | CO2 |
| `field5` | PM2.5 |

The Prediction Service also accepts normalized names such as `temperature`, `humidity`, `co2`, and `pm25`.

## Catalog Service Integration

At startup, the service registers itself through:

```text
POST /services/register
```

Payload shape:

```json
{
  "service_id": "prediction-service",
  "service_name": "prediction-service",
  "type": "prediction",
  "endpoint": "http://prediction-service:8003",
  "health_endpoint": "/health"
}
```

Optional heartbeat support is available through:

```text
PUT /services/{service_id}/heartbeat
```

Enable it with:

```bash
export ROOM_CATALOG_HEARTBEAT_ENABLED=true
```

## Local Run

Install dependencies:

```bash
cd services/prediction
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the service:

```bash
OUTDOOR_AQI_TOKEN="your-token-here" \
ROOM_CATALOG_BASE_URL="http://localhost:8001" \
THINGSPEAK_ADAPTER_BASE_URL="http://localhost:8000" \
uvicorn app.main:app --host 0.0.0.0 --port 8003
```

Check health:

```bash
curl http://localhost:8003/health
```

## Docker Run

Build and run the Prediction Service:

```bash
docker compose --profile app up --build prediction
```

If the full stack uses different service names, override these variables:

```bash
ROOM_CATALOG_BASE_URL="http://<catalog-host>:8001"
THINGSPEAK_ADAPTER_BASE_URL="http://<adapter-host>:8000"
OUTDOOR_AQI_TOKEN="your-token-here"
```

## Training

Train from a CSV file:

```bash
python3 services/prediction/train.py --csv-path /path/to/data.csv
```

Train from a ZIP archive:

```bash
python3 services/prediction/train.py --zip-path /path/to/archive.zip
```

The trainer:

- renames dataset fields
- aggregates repeated timestamps
- resamples to 5-minute intervals
- creates lag, rolling, and trend features
- trains a multi-output model for temperature, humidity, CO2, and PM2.5
- saves the model to `services/prediction/model/model.joblib`

Generated model files are ignored by git. If a trained model is not present, the service falls back to the heuristic baseline forecaster.

## Project Structure

```text
services/prediction/
|-- app/
|   |-- clients.py
|   |-- config.py
|   |-- forecasting.py
|   |-- main.py
|   |-- risk.py
|   |-- schemas.py
|   |-- service.py
|   `-- training.py
|-- docs/
|   `-- api-contract.md
|-- Dockerfile
|-- README.md
|-- requirements.txt
`-- train.py
```

## Notes

- The Prediction Service is designed to be called by the Decision Service, not by MQTT.
- The ThingSpeak Adapter must be running before predictions can use real room history.
- `OUTDOOR_AQI_TOKEN` is required for live Torino AQI.
- Model quality can be improved later without changing the service contract.
