# Catalog Service Design (No DSL Version)

## 1. System Overview

The Catalog Service is responsible for:

- Device Registry (Sensors + Actuators)
- Service Registry
- Room Configuration Management
- Basic Policy Storage (non-DSL)
- Aggregation API (read model)

This service DOES NOT execute logic or interpret rules.

---

## 2. Architecture

Catalog Service
 ├── API Layer (FastAPI)
 ├── In-Memory Cache (indexed dict)
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

## 4. Device Modeling 

Devices have these two types with different calsses:

- sensor
- actuator

---

## 4.1 Sensor Model(device.json)

```json
{
  "key": "temp_1",
  "name": "temp_1",
  "device_class": "temperature",
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

## 4.2 Actuator Model
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

```json
"devices":[
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


---

## 5.3 Heartbeat

```text
PUT /devices/{device_id}/heartbeat
```
```json
{
  "device_id": "temp_1",
  "status": "online",
  "value": 27.5
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

## Model

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

POST /rooms
GET /rooms/{room_id}
PUT /rooms/{room_id}
DELETE /rooms/{room_id}

---


# 7. POLICY

Policies are stored as structured data only.

No evaluation logic in this service.

## Model
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
## Model
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
## Model
```json
{
  "service_id": "decision_service",
  "service_name": "decision_service",
  "type": "decision",
  "endpoint": "http://decision-service",
  "status": "online",
  "last_seen": 1710000000
}
```

## APIs

POST /services/register
PUT /services/{service_id}/heartbeat


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
  "room_id": "room1",
  "sensors": [],
  "actuators": [],
  "policies": [],
  "conflicts": [],
  "energy_mode": "NORMAL",
  "schedule": {}
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
