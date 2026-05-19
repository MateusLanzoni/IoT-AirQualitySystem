# IoT Air Quality System

This branch focuses on the sensor side, MQTT adaptor, and the API-driven data flow between services.
The most important path is:

Catalog Service -> Sensor Service -> MQTT Broker -> Adaptor -> ThingSpeak

The API layer is the source of truth for device metadata, while sensor simulation parameters are kept in `sensor_value_config.yaml`.

## What this branch contains

- `main_sensor.py`: sensor simulator entrypoint
- `main_adaptor.py`: FastAPI adaptor entrypoint
- `components/mqtt/`: shared MQTT topic constants and gateway
- `components/sensor/`: sensor entities
- `components/actuator/`: actuator entities
- `components/drivers/`: simulated hardware drivers
- `components/adaptor/`: MQTT ingress, ThingSpeak egress, and adaptor API
- `catalog_service/`: device registry and service registry API
- `decision_service/`: decision engine and MQTT command handling

## Architecture

### 1. Sensor flow

1. `main_sensor.py` fetches device definitions from the Catalog Service `GET /devices`.
2. It merges local sensor behavior from `sensor_value_config.yaml`.
3. `SensorDriver` generates smooth readings with daily trend, actuator influence, and bounded jitter.
4. `MQTTGateway` publishes telemetry to MQTT topics.

### 2. Adaptor flow

1. `main_adaptor.py` starts the adaptor API, MQTT ingress, and ThingSpeak egress.
2. Ingress subscribes to configured MQTT topics.
3. Egress maps MQTT topics to ThingSpeak fields through `components/adaptor/config.yaml`.
4. Data is pushed to ThingSpeak in bulk update format.

### 3. API flow

The adaptor API exposes historical telemetry from ThingSpeak:

- `GET /health`
- `GET /api/v1/history?roomid=room1&starttime=...&endtime=...`

This branch treats the API as the key integration point for reading historical room data.

## API Overview

### Adaptor API

Base location:

```text
components/adaptor/api.py
```

Endpoints:

#### `GET /health`

Returns service status.

Example response:

```json
{
  "status": "ok",
  "service": "thingspeak_adaptor_api"
}
```

#### `GET /api/v1/history`

Returns ThingSpeak history for a room and time range.

Query parameters:

- `roomid`: target room, for example `room1`
- `starttime`: ISO 8601 start timestamp
- `endtime`: ISO 8601 end timestamp

Example:

```bash
curl "http://localhost:8000/api/v1/history?roomid=room1&starttime=2026-05-07T16:00:00Z&endtime=2026-05-07T17:00:00Z"
```

Internal behavior:

- the API loads `components/adaptor/config.yaml`
- `ThingSpeakProvider` reads channel mapping from that config
- data is queried from ThingSpeak and returned as JSON

## MQTT and Topic Layout

### Topic prefix

The shared namespace is defined in `components/mqtt/const.py`:

```text
airguard/room1
```

### Telemetry topics

The sensor gateway publishes telemetry like:

```text
airguard/room1/telemetry/device/temp_1
airguard/room1/telemetry/device/humi_1
airguard/room1/telemetry/device/co2_1
airguard/room1/telemetry/device/pm25_1
```

### Command topics

The decision side uses command topics like:

```text
airguard/room1/command/device/ac_1
airguard/room1/command/device/fan_1
```

## ThingSpeak Mapping

Mapping is defined in:

```text
components/adaptor/config.yaml
```

Important rules:

- `roomid` selects the channel by matching topics that contain `/{roomid}/`
- history response keeps raw ThingSpeak fields (`created_at`, `field1`, `field2`, ...)
- `field2` to `field7` usually map to telemetry or actuator topics
- topic strings must match exactly
- unsupported topics are dropped by egress

Example mapping:

```yaml
channels:
  - channel_id: 3319669
    write_api_key: "..."
    fields:
      field1: "airguard/room1"
      field2: "airguard/room1/telemetry/device/temp_1"
      field3: "airguard/room1/telemetry/device/humi_1"
      field4: "airguard/room1/telemetry/device/co2_1"
      field5: "airguard/room1/telemetry/device/pm25_1"
      field6: "airguard/room1/telemetry/device/ac_1"
      field7: "airguard/room1/telemetry/device/fan_1"
```

## Sensor Simulation

Sensor behavior is configured in:

```text
sensor_value_config.yaml
```

Each sensor defines:

- `base_val`
- `noise`
- actuator effects such as `ac_effect`, `fan_effect`, `window_effect`
- minimum values such as `ac_min`, `fan_min`, `window_min`
- smoothing settings such as `max_step_ratio` and moving average window

The current driver uses:

- a 24-hour sine trend
- a bounded per-update step limit
- a short moving average for extra smoothing

## Services

### Catalog Service

Catalog Service provides the device registry and service registry.
It is the source of truth for sensor and actuator metadata.

Key endpoints:

- `GET /devices`
- `POST /services/register`
- `DELETE /services/{service_id}`

### Decision Service

Decision Service receives sensor events and publishes control commands.
It listens to MQTT topics for sensor state and actuator status.

## Quick Start

### 1. Start Catalog Service

```bash
cd catalog_service
pip install -r requirements.txt
python main.py
```

### 2. Start Sensor Service

```bash
cd /Users/markus/Documents/IoT-AirQualitySystem
source .venv/bin/activate
python main_sensor.py
```

### 3. Start Adaptor Service

```bash
cd /Users/markus/Documents/IoT-AirQualitySystem
source .venv/bin/activate
python main_adaptor.py
```

### 4. Start Decision Service

```bash
cd decision_service
pip install -r requirements.txt
python main.py
```

## Docker

If you want to run the full stack with Docker Compose:

```bash
cd /Users/markus/Documents/IoT-AirQualitySystem
docker-compose up -d
```

To follow adaptor logs:

```bash
docker-compose logs -f adaptor-service
```

## Useful Checks

### Check sensor history API

```bash
curl "http://localhost:8000/api/v1/history?roomid=room1&starttime=2026-05-07T16:00:00Z&endtime=2026-05-07T17:00:00Z"
```

### Check decision service status

```bash
curl http://localhost:8002/status
```

### Trigger a mock decision event

```bash
curl -X POST http://localhost:8002/trigger/room1 \
  -H "Content-Type: application/json" \
  -d @decision_service/data/mock_sensor_event.json
```

## Project Structure

```text
📦 IoT-AirQualitySystem
├── main_sensor.py
├── main_adaptor.py
├── sensor_value_config.yaml
├── catalog_service/
├── decision_service/
└── components/
    ├── actuator/
    ├── adaptor/
    ├── drivers/
    ├── mqtt/
    ├── registry/
    └── sensor/
```

## Notes

- The adaptor API is the main part of this branch.
- The sensor pipeline depends on the Catalog Service `/devices` response.
- The ThingSpeak mapping is strict: topic strings must match exactly.
- If a topic is not found in the routing table, egress skips it.
