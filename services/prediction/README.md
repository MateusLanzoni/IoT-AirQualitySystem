# Prediction Service

This service implements the proposal-aligned ML forecasting workflow for AirGuard.

## Proposal-Aligned Responsibilities

- Register itself in `Room Catalog` via REST on startup
- Optionally send service heartbeat updates to `Room Catalog`
- Accept forecast requests from `Decision Service` via REST
- Retrieve recent and historical indoor sensor data from `ThingSpeak Adapter` via REST
- Retrieve current outdoor AQI for Turin from the outdoor API gateway via REST
- Produce short-term forecasts for temperature, humidity, CO2, and PM2.5
- Return prediction results to `Decision Service` via REST

## Runtime Flow

1. `Decision Service` calls `POST /predict` with a `room_id`
2. `Prediction Service` fetches room history from `ThingSpeak Adapter`
3. `Prediction Service` fetches current outdoor AQI for Turin
4. `Prediction Service` runs the forecasting model
5. `Prediction Service` returns forecasted IAQ trends to `Decision Service`

## Endpoints

### `GET /health`

Returns service health, model source, dependency URLs, and Room Catalog registration state.

### `POST /predict`

Request body:

```json
{
  "room_id": "room-101",
  "horizon_minutes": 15,
  "lookback_points": 12
}
```

The service itself retrieves:
- recent and historical indoor data
- latest outdoor AQI for Turin

## Final Integration Notes

- `ThingSpeak Adapter` is expected to expose a history endpoint that can be filtered by `room_id`
- `Outdoor AQI` is currently configured for Turin using the WAQI-compatible feed path
- for production, set `OUTDOOR_AQI_TOKEN` in the environment
- the local mock services and demo scripts are for development only and should not be part of the final PR

## Training

Train from CSV:

```bash
python3 services/prediction/train.py --csv-path /path/to/data.csv
```

Train from ZIP:

```bash
python3 services/prediction/train.py --zip-path "/Users/syedumer/Downloads/archive (2).zip"
```

The trainer:
- renames dataset columns
- aggregates multiple sensor rows by timestamp
- resamples to 5-minute intervals
- creates lag, rolling, and trend features
- trains a multi-output regressor for `temperature`, `humidity`, `pm25`, and `co2`
- saves the model to `services/prediction/model/model.joblib`
