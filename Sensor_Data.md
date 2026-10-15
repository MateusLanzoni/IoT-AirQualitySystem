This branch focuses on the sensor side, MQTT adaptor, and external integration flow.
The most important path is:

Sensor Service -> MQTT Broker -> Adaptor -> ThingSpeak

### 1. Sensor flow

### 1. `core/` — Central Event-Driven Backbone
* **Primary Responsibility:** Serves as the central nervous system of the edge gateway by providing an asynchronous, non-blocking internal publish-subscribe mechanism (`core/event_bus.py`).
* **Decoupling:** Completely eliminates direct dependencies between sensors, actuators, and communication protocols. Components only interact with the `EventBus`.
* **Resilience & Fault Isolation:** Event listeners are wrapped and dispatched as isolated background `asyncio` tasks (`_async_dispatch_safely`). If a single device driver or listener raises an exception, it is logged without crashing the event loop or affecting other devices.
* **Key Events:**
  * `EVENT_STATE_CHANGED`: Dispatched whenever a sensor reads a new value or an actuator toggles its state.
  * `EVENT_COMMAND_RECEIVED`: Dispatched when an external command is received by the gateway for device execution.

### 2. `components/` — Modular Subsystems & Services
* **Primary Responsibility:** Contains all modular building blocks that implement physical device models, protocol gateways, simulation engines, and external cloud adaptors.
* **Sub-module Breakdown:**
  * **`sensor/`**: Environmental sensor domain logic and telemetry acquisition.
  * **`actuator/`**: Controllable appliance domain logic and state transitions.
  * **`drivers/`**: Hardware simulation engine (`SensorDriver`, `ActuatorDriver`) modeling daily diurnal cycles, bounded jitter, and real-time physical interactions between actuators and environment.
  * **`mqtt/`**: Edge network gateway (`MQTTGateway`) bridging internal `EventBus` events with external MQTT broker topics.
  * **`adaptor/`**: Cloud synchronization service ingesting MQTT telemetry, queuing data in thread-safe buffers, pushing bulk batches to ThingSpeak, and exposing a REST query API.
  * **`registry/`**: Device catalog integration client for dynamically fetching device descriptors and room layouts.

### 3. `sensor` (`components/sensor/`) — Environmental Telemetry Ingestion
* **Primary Responsibility:** Manages the lifecycle, metadata, and data collection of environmental sensors (e.g., Temperature, Humidity, CO₂, PM2.5, AQI).
* **Core Components:**
  * `SensorEntityDescription`: Dataclass defining static device metadata (unique `key`, `name`, `room_id`, `device_class`, `native_unit_of_measurement`).
  * `SensorEntity`: Abstract base entity providing standard properties and async polling hooks.
  * `AirguardSensor`: Concrete implementation that periodically polls `SensorDriver.read_data()`, evaluates whether the metric changed, updates internal state, and fires `EVENT_STATE_CHANGED` onto the `EventBus`.

### 4. `actuator` (`components/actuator/`) — Device Actuation & State Management
* **Primary Responsibility:** Manages controllable environmental appliances (e.g., Fans, Air Conditioners, Windows) and executes command actions.
* **Core Components:**
  * `ActuatorEntityDescription`: Dataclass defining actuator metadata (`key`, `name`, `device_class`, `room_id`).
  * `ActuatorEntity`: Abstract base entity defining `async_turn_on()`, `async_turn_off()`, and state properties.
  * `AirguardActuator`: Concrete implementation that:
    1. Subscribes to `EVENT_COMMAND_RECEIVED` on the `EventBus`.
    2. Filters incoming commands targeting its specific `device_id` and `room_id`.
    3. Invokes driver commands (`set_state(True/False)` via `ActuatorDriver`).
    4. Updates its internal state and fires `EVENT_STATE_CHANGED` onto the `EventBus` to notify external gateways and update the environment simulation physics.

---

## End-to-End Data & Control Flows

### 1. Telemetry Data Flow
1. **Periodic Sampling:** `main_sensor.py` triggers `sensor.async_update()` for all configured sensors.
2. **Data Acquisition:** `AirguardSensor` reads the current value from its `SensorDriver` (incorporating simulated physical effects and daily sine trends).
3. **Internal Event Emission:** If the value changes, `AirguardSensor` emits `EVENT_STATE_CHANGED` to `EventBus`.
4. **MQTT Bridge:** `MQTTGateway` receives the event and publishes JSON telemetry to `airguard/{room_id}/telemetry/device/{device_id}`.
5. **Adaptor Ingestion:** `main_adaptor.py` subscribes to MQTT telemetry, buffers the readings, and batches writes to ThingSpeak via `egress_to_tspeak.py`.

### 2. Actuator Control Flow
1. **External Command:** External services (e.g., Decision Service, Dashboard) publish a command to `control/{room_id}/{device_id}/command`.
2. **MQTT Gateway Reception:** `MQTTGateway` parses the topic and JSON payload, then fires `EVENT_COMMAND_RECEIVED` on the `EventBus`.
3. **Actuator Execution:** The corresponding `AirguardActuator` receives the event, executes `async_turn_on()` or `async_turn_off()`, and updates the underlying `ActuatorDriver`.
4. **State Broadcast & Environmental Feedback:** The actuator fires `EVENT_STATE_CHANGED`, updating MQTT telemetry subscribers and feeding back into `SensorDriver` to simulate temperature/air quality adjustments (e.g., turning on the AC gradually lowers temperature).

---

## API Overview

### Adaptor API

Base location:

```text
components/adaptor/api.py
```

Endpoints:

## MQTT & Topic Specification

### 1. Topic Namespaces
* **Telemetry Prefix:** `airguard/{room_id}/telemetry/device/{device_id}`
* **Control Prefix:** `control/{room_id}/{device_id}/command`

### 2. Telemetry Payload Format
Published by `MQTTGateway` on state updates:
```json
{
  "device_id": "temp_1",
  "value": 24.85,
  "timestamp": 1729000000
}
```

### 3. Control Command Format
Sent by external services to command an actuator:
```json
{
  "device_id": "ac_1",
  "command": "TURN_ON",
  "target_state": "ON",
  "reason": "high_temperature_threshold",
  "timestamp": 1729000000
}
```
* Supported commands: `TURN_ON` / `turn_on`, `TURN_OFF` / `turn_off`.

---

## Adaptor REST API

The ThingSpeak adaptor exposes REST endpoints for historical telemetry inspection:

* `GET /health` — Service health check.
* `GET /api/v1/history?roomid={room_id}&starttime={iso}&endtime={iso}` — Historical sensor readings from ThingSpeak.
* `GET /api/thingspeak-rooms` — Discovered room channels and field mappings.

### Example Query
```bash
curl "http://localhost:8000/api/v1/history?roomid=room1&starttime=2026-10-15T12:00:00Z&endtime=2026-10-15T16:00:00Z"
```

---

## Quick Start

### 1. Prerequisites
* Python 3.11+
* Running MQTT Broker (e.g., Mosquitto on `localhost:1883`)

### 2. Local Execution

```bash
# Setup virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Terminal 1: Start Edge Sensor Node
python main_sensor.py

# Terminal 2: Start Adaptor & History API Service
python main_adaptor.py
```

### 3. Docker Deployment

To launch the full system stack (Mosquitto, Edge Sensors, Adaptor, and dependent microservices):
```bash
docker-compose up -d
```

To inspect service logs:
```bash
docker-compose logs -f sensor-service
docker-compose logs -f adaptor-service
```
