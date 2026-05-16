# Catalog Service Design

## 1. System Overview

The Catalog Service is responsible for:

- Device management (Sensors + Actuators)
- Service Registry
- Room Configuration Management
- Basic Policy Storage 
- Aggregation API (read model)

This service DOES NOT execute logic or interpret rules.

---

## 2. Architecture

Catalog Service
 ├── API Layer (FastAPI)
 ├── DTO Layer (API Schema)
 ├── DO Layer (Domain Object / Storage Model)
 ├── In-Memory Cache (indexed map)
 ├── JSON Storage (persistent)
---

## 3. Storage Design

Data MUST be separated:

data/
 ├── devices.json
 ├── rooms.json
 ├── policies.json
 ├── conflicts.json
 ├── services.json

---
## API RESPONSE STANDARD
Global Response Format
```json
{
  "code": 0,
  "msg": "success",
  "data": {}
}
```

code = 0 → success
code != 0 → error, msg shows the error message.

---

## 4. Device Modeling 

Devices have these two types with different calsses:

- sensor
- actuator

---
### 4.1 Layer Definition
DTO (API Layer): Used for request/response

DO (Domain Object): Used for internal storage & cache -> device.json

### 4.2.1 DO Model: Sensor Model(device.json)

```json
{
  "device_id": "temp_1",
  "device_name": "temp_1",
  "category": "sensor",
  "type": "temperature",
  "room_id": "room1",
  "native_unit_of_measurement": "℃",
  "status": "online",
  "last_value": 26.5,
  "unit": "°C",
  "last_seen": 1710000000,
  "created": 1710000000,
  "modified": 1710000000,
  "metadata": {}
}
```

### 4.2.2 DO Model: Actuator
```json
{
  "device_id": "ac_1",
  "device_name": "ac_1",
  "category": "actuator",
  "type": "AC",
  "room_id": "room1",
  "desired_state": "OFF",
  "actual_state": "ON",
  "status": "online",
  "last_seen": 1710000000,
  "created": 1710000000,
  "modified": 1710000000,
  "metadata": {}
}
```

### 4.3 mapping rule
| DO field     | DTO field                   |
| ------------ | --------------------------- |
| device_id    | key                         |
| device_name  | name                        |
| device_class | device_class                |
| category     | category                    |
| room_id      | room_id                     |
| unit         | unit                        |
| last_value   | (optional external mapping) |



# 5. Device Lifecycle

## Devices MUST support:

- get device infor from the static docs
- Update (manual, temporary)
- Heartbeat
- Auto-offline detection
- Deregistration

## 5.1 get Device
```text
GET /devices
```

response:
```json
{
  "code": 0,
  "msg": "success",
  "data": [
  {
    "key": "ac_1",
    "name": "ac_1",
    "device_class": "AC", // AC, FANS, WINDOWS
    "room_id": "room1",
    "category": "actuator",  //Actuator, sensor
    "unit": ""
  },
  {
    "key": "temp_1",
    "name": "temp_1",
    "category": "sensor",
    "device_class": "temperature",
    "room_id": "room1",
    "unit": "°C",
  }
  ]
}
```

---

## 5.2 Update Device
```text
PUT /devices/{device_id}
```

```json
{
  "key": "temp_1",
  "name": "temp_1",
  "device_class": "temperature",
  "room_id": "room1",
  "category": "sensor",
  "unit": "℃"
}
```
Response:
```json
{
  "code": 0,
  "msg": "created",
  "data": null
}
```

---

## 5.3 Heartbeat

1. System Logic Overview:

The system is driven by a Scheduler, which actively pulls data from external services and synchronizes it to both an in-memory cache and a persistent storage layer (JSON file).

2. Scheduler Behavior
- Execution Frequency:
Runs every N seconds (e.g., 10 seconds, configurable).
- Workflow:
  - Fetch: The scheduler calls an external service API (e.g., ThingSpeak).
  - In-Memory Update: The retrieved state is immediately updated in a local indexed map (cache).
  - Persistence: Based on the defined write strategy, the updated state is asynchronously persisted to devices.json.

Pulled Data from [ThingSpeak](https://api.thingspeak.com/channels/{channel_id}/feeds.json):

```json
{
  "channel": {
    "id": 3319669,
    "name": "IAQ",
    "description": "Temperature & Humidity Sensor\r\nMeasuring indoor temperature and humidity\r\nAir Quality Sensor（CO₂, PM2.5)\r\nMeasuring indoor air quality\r\n",
    "latitude": "4.7",
    "longitude": "-74.0",
    "field1": "room_id",
    "field2": "Temperature",
    "field3": "Humidity",
    "field4": "CO2",
    "field5": "PM25",
    "field6": "AC_Status",
    "field7": "Fan_Status",
    "created_at": "2026-03-30T20:27:47Z",
    "updated_at": "2026-04-16T23:50:30Z",
    "elevation": "239(Turin)",
    "last_entry_id": null
  },
  "feeds": []
}

```

Behavior:

update last_seen
if sensor → update last_value
if actuator → update actual_state (optional)

--- 


## 5.4 Auto Offline
``` text
if now - last_seen > timeout:
    status = offline
```

---


## 5.5 Delete Device
```text
DELETE /devices/{device_id}
```
---

# 6. ROOM CONFIGURATION

## Model(rooms.json)

``` json
{
  "room_id": "room1",
  "device_ids": ["ac_1", "temp_1"],
  "energy_mode": "NORMAL",
  "schedule": {
    "start": "08:00",
    "end": "23:00"
  }
}
```

## CRUD

GET /rooms
POST /rooms
GET /rooms/{room_id}
PUT /rooms/{room_id}
DELETE /rooms/{room_id}

---


# 7. POLICY

Policies are stored as structured data only.

No evaluation logic in this service.

## Model(policies.json)
```json
{
  "policy_id": "p1",
  "room_id": "room1",
  "metric": "temperature",
  "operator": ">",
  "value": 26,
  "target_device": "ac_1",
  "target_state": "ON",
  "priority": 2
}
```

## CRUD

POST /policies
GET /policies?room_id=xxx
PUT /policies/{policy_id}
DELETE /policies/{policy_id}

--- 

# 8. CONFLICT RULES
## Model(conflicts.json)
```json
{
  "conflict_id": "c1",
  "room_id": "room1",
  "rule": "mutually_exclusive",
  "strategy": "prefer_higher_priority"
}
```

## CRUD

POST /conflicts
GET /conflicts?room_id=xxx
PUT /conflicts/{id}
DELETE /conflicts/{id}

# 9. SERVICE REGISTRY
## Model(services.json)
```json
{
  "service_id": "decision_service",
  "service_name": "decision_service",
  "endpoint": "http://decision-service",
  "health_endpoint": "/health",
  "status": "online",
  "last_seen": 1710000000
}
```

## APIs

GET /services

response:
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "service_id": "decision_service",
      "service_name": "decision_service",
      "type": "decision",
      "endpoint": "http://decision-service",
      "health_endpoint": "/health",
      "status": "online",
      "last_seen": 1710000000
    }
  ]
}
```

POST /services/register
```json
{
  "service_id": "decision_service",
  "service_name": "decision_service",
  "type": "decision",
  "endpoint": "http://decision-service",
  "health_endpoint": "/health"
}
```

DELETE /services/{service_id}

Health Check Scheduler
```text
Every N seconds (e.g., 5s):
  for each service:
      call endpoint + health_endpoint
```

Health Check Logic
``` python
for service in services:
    try:
        resp = GET(service.endpoint + service.health_endpoint, timeout=1s)

        if resp.status_code == 200:
            service.status = "online"
            service.last_seen = now()

            if "load" in resp.json():
                service.load = resp.json()["load"]

        else:
            service.status = "degraded"

    except:
        service.status = "offline"
```
200 OK           → online
non-200 response → degraded
timeout/error    → offline

health_check_interval = 5s
request_timeout = 1s

## Auto Offline

Same as device

# 10. AGGREGATION API 

## GET /room/{room_id}

This API MUST aggregate from:

- rooms.json
- devices.json
- policies.json
- conflicts.json
- cache

## Aggregation Logic
1. Load room
2. Resolve device_ids → full device objects
3. Separate:
    - sensors
    - actuators
4. Load policies by room_id
5. Load conflicts by room_id
6. Merge cache overrides

### Response
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "room_id": "room1",
    "sensors": [
      {
        "key": "temp_1",
        "name": "temp_1",
        "category": "sensor",
        "device_class": "temperature",
        "room_id": "room1",
        "unit": "°C"
      }
    ],
    "actuators": [
      {
        "key": "ac_1",
        "name": "ac_1",
        "device_class": "AC",
        "room_id": "room1",
        "category": "actuator",
        "unit": ""
      }
    ],
    "policies": [],
    "conflicts": [],
    "energy_mode": "NORMAL",
    "schedule": {}
  }
}
```
---

# 11. MERGE PRIORITY
- Cache (latest)
- JSON (persistent)

# 12. WRITE STRATEGY

All writes MUST:

- Update cache
- Persist to JSON

# 13. CONSISTENCY MODEL
- Eventual consistency
- Cache-first read
- Write-through

# 14. PERFORMANCE REQUIREMENTS
- O(1) lookup via cache
- Indexed maps required
- No full JSON scan per request

# 15. DESIGN PRINCIPLES
- No business logic (no rule evaluation)
- Catalog = data source only
- Device model MUST distinguish sensor vs actuator
- Aggregation API is read-only composition
- System is extensible for Decision Service
