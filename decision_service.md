# Decision Service (Full Spec: Policy + State Machine + Priority + Energy Mode)

## Overview

This service is an event-driven decision engine for IoT smart rooms.

It integrates:

* Policy Engine (config-driven decisions)
* Priority & Conflict Resolution
* Energy Mode (power optimization)
* State Machine (reliable execution)

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


# 1. Input Interfaces

## 1.1 MQTT - Sensor State (Primary Trigger)

**Broker:** configured externally
**Topic:**

```text
airguard/{room_id}/telemetry/{device_type}/{device_id}
```

**Payload:**

```json
{
  "device_id": "temp_1",
  "value": 28.5,
  "timestamp": 1234567890
}
```

---

## 1.2 MQTT - Device Status (Execution Feedback)

**Topic:**

```text
airguard/{room_id}/state/device/{device_id}
```

**Payload:**

```json
{
  "device_id": "temp_1",
  "state": "ON",
  "timestamp": 1234567890
}
```

**Result values:**

```text
SUCCESS | FAILURE
```

---

## 1.3 REST - Prediction Service (Pull)

**Method:**

```http
GET /prediction/{room_id}
```

**Base URL:**

```text
http://prediction-service
```

**Response:**

```json
  "code": 0,
  "msg": "success",
  "data": {
    "timestamp": 1712577600123,
    "predictions": {
      "temperature": {
        "value": 30,
        "trend": "RISING", // RISING | FALLING | STABLE
        "target_state": "ON", // ON,OFF,STABLE
        "devices": ["fans-1", "AC-1", "windows-1"]
      },
      "co2": {
        "value": 1200,
        "trend": "RISING",
        "target_state": "ON", // ON,OFF,STABLE
        "devices": ["AC-1", "windows-1"]
      }
    }
  }
```

---

## 1.4 REST - Room Catalog Service（pull）

**Method:**

```http
GET /room/{room_id}
```

**Base URL:**

```text
http://room-catalog-service
```

**Response:**

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "room_id": "room1",
    "devices": [
      {
        "device_id": "ac_1",
        "type": "AC",
        "initial_state": "OFF"
      },
      {
        "device_id": "fan_1",
        "type": "FAN",
        "initial_state": "OFF"
      },
      {
        "device_id": "window_1",
        "type": "WINDOW",
        "initial_state": "CLOSED"
      }
    ],
    "policies": [
      {
        "metric": "temperature",
        "condition": "> 26",
        "priority": 2,
        "target": { "device": "ac_1", "state": "ON" }
      },
      {
        "metric": "co2",
        "condition": "> 1000",
        "priority": 1,
        "target": { "device": "window_1", "state": "OPEN" }
      }
    ],
    "conflicts": [
      {
        "rule": "mutually_exclusive"，
        "strategy": "prefer_higher_priority"
      }
    ],
    "energy_mode": "NORMAL",
    "schedule": {
      "start": "08:00",
      "end": "23:00"
    }
  }
}
```

---

# 2. Output Interfaces

## 2.1 MQTT - Control Command

**Topic:**

```text
control/{room_id}/{device_id}/command
```

**Payload:**

```json
{
  "device_id": "ac_1",
  "command": "TURN_ON",
  "target_state": "ON",
  "reason": "temperature_high",
  "timestamp": 1712577600123
}
```

---

## 2.2 MQTT - Alert

**Topic:**

```text
alert/{room_id}
```

**Payload:**

```json
{
  "type": "DEVICE_FAILURE",
  "device_id": "ac_1",
  "message": "Failed to turn on device",
  "timestamp": 1712577600123
}
```

---

## 2.3 MQTT - Decision Log

**Topic:**

```text
event/{room_id}/decision_log
```

**Payload:**

```json
{
  "room_id": "room1",
  "decisions": [
    {
      "device_id": "window_1",
      "target": "OPEN",
      "priority": 1
    }
  ],
  "filtered_actions": [
    {
      "device_id": "ac_1",
      "reason": "conflict_with_window"
    }
  ],
  "energy_mode": "NORMAL",
  "timestamp": 1712577600123
}
```

---

# 3. Processing Flow

```text
1. Receive sensor state (MQTT)
2. Validate timestamp and data freshness
3. Filter abnormal metric values
4. Fetch prediction (REST)
5. Fetch room configuration (REST)
6. Evaluate policies → candidate actions
7. Apply energy mode adjustments
8. Resolve conflicts (priority-based)
9. Generate final target states
10. Run state machine transitions
11. Publish control commands (MQTT)
12. Receive device feedback (MQTT)
13. Update state store
14. Publish logs and alerts
```

---

# 4. Policy + Priority + Conflict Resolution

## Candidate Actions

```json
[
  { "device": "window_1", "state": "OPEN", "priority": 1 },
  { "device": "ac_1", "state": "ON", "priority": 2 },
  { "device": "fan_1", "state": "ON", "priority": 3 }
]
```

---

## Conflict Rule

```json
{
  "devices": ["ac_1", "window_1", "fan_1"],
  "rule": "mutually_exclusive"
}
```

---

## Resolution Result

```json
{
  "window_1": "OPEN"
}
```

---

# 5. Energy Mode

## Modes

```text
NORMAL
ENERGY_SAVING
```

## Configuration
```text
{
  "energy_mode": "ENERGY_SAVING"
}
```

## Action Suppression
Avoid turning ON high-power devices unless critical

Implementation/Modify policy evaluation:
```text
if energy_mode == "ENERGY_SAVING":
    adjust_thresholds()
    lower_priority_of("AC")
```

## Critical Override
```text
if co2 > 2000 or temperature > 35:
    ignore energy_mode
```

---

## Behavior

* Increase temperature thresholds
* Lower priority of high-energy devices (AC)
* Prefer low-cost devices (fan, window)

---
## Priority Adjustment (Dynamic)

Final priority:

effective_priority = base_priority + energy_penalty

Example:

AC priority = 2 + 2 = 4
FAN priority = 3 + 0 = 3


---

# 6. Conflict Resolution
## Supported Strategies
- prefer_higher_priority
- prefer_lower_energy
- prefer_comfort

## Algorithm
1. Sort by effective_priority
2. Iterate
3. If conflict:
    apply strategy
    reject lower priority

# 7. State Machine

## States

```text
OFF
TURNING_ON
ON
TURNING_OFF
ERROR
```

---

## Transition

```python
if current == "OFF" and target == "ON":
    → TURNING_ON + SEND TURN_ON
```

---

## Feedback Handling

```python
SUCCESS → ON / OFF
FAILURE → ERROR
```

## Timeout Handling

```python
if state == "TURNING_ON" and now - last_action_time > 10s:
    → ERROR
```

---

# 8. In-Memory State Store

```python
device_store = {
    "room1": {
        "ac_1": {
            "state": "ON",
            "last_action_time": 1712577600123
        }
    }
}
```
## Config Cache
```text
config_cache = {
    "room_id": {
        "config": {...},
        "version": "v1",
        "last_fetch": 1712577600123
    }
}
```

Rules
Refresh if TTL exceeded (e.g. 60s)
Refresh if version changed


---

# 9. Key Guarantees

* Idempotent commands
* Conflict-free actions
* Energy-aware decisions
* Robust to partial data
* Event-driven low latency

---

# 10. Key Principle

> Policy decides the desired state.
> Priority resolves conflicts.
> State Machine ensures safe execution.
