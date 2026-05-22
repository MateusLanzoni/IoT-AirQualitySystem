# IoT Air Quality System

This branch focuses on the sensor side, MQTT adaptor, and external integration flow.
The most important path is:

Sensor Service -> MQTT Broker -> Adaptor -> ThingSpeak

The API layer is the source of truth for device metadata, while sensor simulation parameters are kept in `sensor_value_config.yaml`.

## Architecture

### 1. Sensor flow

1. `main_sensor.py` loads local sensor behavior from `sensor_value_config.yaml`.
2. Both sensors and actuators are initialized with event bus listeners.
3. `SensorDriver` generates smooth readings with daily trend, actuator influence, and bounded jitter.
4. `MQTTGateway` publishes telemetry from both sensors and actuators to device topics.
5. `MQTTGateway` also listens for incoming commands on `control/{room_id}/{device_id}/command` and routes them to actuators.

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

### Topic prefixes

Two namespaces are used:

- **Internal telemetry:** `airguard/room1` (defined in `components/mqtt/const.py`)
- **External commands:** `control` (for inbound command requests)

### Telemetry topics

The sensor gateway publishes telemetry to device topics:

```text
airguard/room1/telemetry/device/temp_1
airguard/room1/telemetry/device/humi_1
airguard/room1/telemetry/device/co2_1
airguard/room1/telemetry/device/pm25_1
airguard/room1/telemetry/device/ac_1
airguard/room1/telemetry/device/fan_1
airguard/room1/telemetry/device/window_1
```

Payload format:
```json
{
  "device_id": "temp_1",
  "value": 25.5,
  "timestamp": 1684860000
}
```

### Command topics

External services send control commands using this topic pattern:

```text
control/{room_id}/{device_id}/command
```

Example:
```text
control/room1/ac_1/command
control/room1/fan_1/command
```

## ThingSpeak Mapping

Mapping is defined in:

```text
components/adaptor/config.yaml
```

Important rules:

- `field1` is used for `room_id`
- `field2` to `field7` map to telemetry or actuator topics
- topic strings must match exactly
- unsupported topics are dropped by egress

Example mapping:

```yaml
channels:
  - channel_id: 3319669
    write_api_key: "..."
    fields:
      field1: "room_id"
      field2: "airguard/room1/telemetry/sensor/temp_1"
      field3: "airguard/room1/telemetry/sensor/humi_1"
      field4: "airguard/room1/telemetry/sensor/co2_1"
      field5: "airguard/room1/telemetry/sensor/pm25_1"
      field6: "airguard/room1/telemetry/actuator/ac_1"
      field7: "airguard/room1/telemetry/actuator/fan_1"
      field1: "room_id"
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

The current driver uses:

- a 24-hour sine trend
- a bounded per-update step limit
- a short moving average for extra smoothing

## Quick Start

### 1. Start Sensor Service

```bash
cd /Users/markus/Documents/IoT-AirQualitySystem
source .venv/bin/activate
python main_sensor.py
```

### 2. Start Adaptor Service

```bash
cd /Users/markus/Documents/IoT-AirQualitySystem
source .venv/bin/activate
python main_adaptor.py
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

## Project Structure

```text
📦 IoT-AirQualitySystem
├── main_sensor.py
├── main_adaptor.py
├── sensor_value_config.yaml
└── components/
    ├── actuator/
    ├── adaptor/
    ├── drivers/
    ├── mqtt/
    ├── registry/
    └── sensor/
```

## External Integration

### Sending Commands

External services can send control commands to devices:

**Topic format:**
```text
control/{room_id}/{device_id}/command
```

**Payload format:**
```json
{
  "device_id": "ac_1",
  "command": "TURN_ON",
  "target_state": "ON",
  "reason": "temperature_high",
  "timestamp": 1684860000
}
```

Supported commands:
- `TURN_ON` / `turn_on` - activate the device
- `TURN_OFF` / `turn_off` - deactivate the device

The command handler normalizes case and routes commands to the appropriate actuator.

## Notes

- The adaptor API is the main part of this branch.
- The ThingSpeak mapping is strict: topic strings must match exactly.
- If a topic is not found in the routing table, egress skips it.
- Commands use `control/{room_id}/{device_id}/command` naming convention for external integration.
- Command payloads support both uppercase and lowercase action names for compatibility.
