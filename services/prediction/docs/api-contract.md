# Prediction Service Contract

## Service Role

The Prediction Service gives the Decision Service a forward-looking view of indoor air quality.

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
- `lookback_points` controls how much indoor history the service requests from ThingSpeak Adapter
- `Decision Service` does not send telemetry history directly in the final design

## Response Rules

- `prediction` always includes `temperature`, `humidity`, `co2`, and `pm25`
- `indoor_latest` reflects the latest usable indoor reading retrieved from ThingSpeak Adapter
- `outdoor` reflects the AQI input used for the forecast
- `risk` is one of `normal`, `warning`, or `critical`
- `summary` is designed for logs, debugging, and later alerting

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
  "name": "Prediction Service",
  "version": "0.2.0",
  "base_url": "http://prediction:8002",
  "endpoints": ["GET /health", "POST /predict"],
  "capabilities": ["short-term-iaq-forecasting", "outdoor-aqi-enrichment"],
  "status": "online"
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
