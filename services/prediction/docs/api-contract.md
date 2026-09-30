# Prediction Service Contract

## Service Role

The Prediction Service gives the Decision Service a forward-looking view of indoor air quality.

Its HTTP interface runs on CherryPy at port `8003`. The successful JSON contracts
remain compatible with the previous FastAPI implementation. Swagger `/docs` is
not provided.

It does not publish actuation commands and it does not decide which device to turn on.

## Caller

- Primary caller: Decision Service
- Startup integration: Room Catalog

## Endpoint Summary

### `GET /health`

Purpose:
- Confirm the service is reachable
- Confirm whether the forecaster is running with a trained model or a baseline fallback
- Confirm whether the service registered successfully in Room Catalog

### `POST /predict`

Purpose:
- Manual/debug request for a short-term forecast for one room

### `GET /prediction/{room_id}`

Purpose:
- Decision Service integration endpoint
- Returns the wrapper format expected by `decision_service/processor.py`

### `GET /outdoor-aqi`

Purpose:
- Outdoor AQI gateway endpoint for Turin
- Uses the same WAQI-compatible client used during prediction

## Request Rules

- `room_id` is required
- `horizon_minutes` should stay between `1` and `180`
- `lookback_points`, when supplied, must stay between `3` and `288`
- `lookback_points` controls how much indoor history the service requests from ThingSpeak Adapter
- `Decision Service` does not send telemetry history directly in the final design

## Response Rules

- `prediction` always includes `temperature`, `humidity`, `co2`, and `pm25`
- `indoor_latest` reflects the latest usable indoor reading retrieved from ThingSpeak Adapter
- `outdoor` reflects the AQI input used for the forecast
- `risk` is one of `normal`, `warning`, or `critical`
- `summary` is designed for logs, debugging, and later alerting

### Error Responses

Errors use JSON `{"detail": ...}`. Validation failures return `422` with an error
list, missing indoor history returns `404`, upstream HTTP/network failures return
`502`, and upstream timeouts return `504`. A configured WAQI outage can still fail
the request. An unset token returns an unconfigured outdoor snapshot and permits
indoor forecasting to continue.

## Team Integration Notes

- The proposal describes Prediction Service as a REST service queried by Decision Service
- The proposal also describes Prediction Service as a consumer of ThingSpeak Adapter and Outdoor AQI APIs
- Prediction Service registers itself in Room Catalog for service discovery, but does not depend on Room Catalog for live sensor history

## Upstream Contracts Expected By Prediction Service

### Room Catalog

- `POST /services/register`
- optional: `PUT /services/{service_id}/heartbeat`

Expected payload:

```json
{
  "service_id": "prediction-service",
  "service_name": "prediction-service",
  "type": "prediction",
  "endpoint": "http://prediction-service:8003",
  "health_endpoint": "/health"
}
```

### ThingSpeak Adapter

- `GET /api/v1/history?roomid=room1&starttime=2026-05-13T10:00:00Z&endtime=2026-05-13T11:00:00Z`

Accepted response shapes:
- `{ "room_id": "...", "points": [...] }`
- `{ "items": [...] }`
- raw list of points

Point fields accepted:
- `timestamp` or `created_at`
- `temperature` or `field2`
- `humidity` or `field3`
- `co2` or `field4`
- `pm25` or `field5`

The field mapping follows the current sensor/adaptor branch:
- `field2`: temperature
- `field3`: humidity
- `field4`: CO2
- `field5`: PM2.5

### Outdoor AQI Gateway

- current implementation is configured to fetch Turin AQI
- gateway endpoint exposed by Prediction Service:
  - `GET /outdoor-aqi`
- default path pattern:
  - `GET https://api.waqi.info/feed/@13202/?token=...`
- the client reads:
  - `data.aqi`

## Model Visibility

`GET /health` includes `model` diagnostics and `last_inference`. `model_source`
indicates the forecaster loaded at startup. `model.loaded` and
`model.self_test == "passed"` indicate artifact validation and an inference probe,
not measured accuracy or successful access to live room data.

`POST /predict` includes `model_diagnostics`; `GET /prediction/{room_id}` adds
`data.model_source` and `data.model_diagnostics` without changing the existing
`data.predictions` wrapper. The per-response source is authoritative for which
model actually produced that forecast.

A model trained for one horizon uses baseline for other horizons with an explicit
`unsupported_horizon` reason. Insufficient recent feature history or model inference
failure likewise uses baseline and reports why. No artifact returns
`artifact_missing` in startup diagnostics. Legacy artifacts must be retrained.

The CSV-trained RF has no historical outdoor AQI training feature variation; it
uses AQI zero during inference. This is separate from the baseline's AQI enrichment.
The forecast reference time is the newest history bin, not necessarily wall-clock
now; `forecast_reference_at` exposes that distinction.
