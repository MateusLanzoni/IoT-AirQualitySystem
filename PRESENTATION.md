# IoT Air Quality System – Technical Presentation

## Executive Summary

The **IoT Air Quality System** is a distributed microservices platform that:
- **Monitors** indoor air quality across rooms (temperature, humidity, CO₂, PM2.5)
- **Predicts** future air quality degradation using machine learning
- **Enforces** automated control policies (ventilation, AC, etc.)
- **Alerts** administrators via web dashboard and Telegram
- **Stores** historical data in the cloud (ThingSpeak)

---

## Table of Contents

1. [Technology Stack](#technology-stack)
2. [Architecture Overview](#architecture-overview)
3. [Core Components](#core-components)
4. [The Alarm System](#the-alarm-system)
5. [The Webpage Dashboard](#the-webpage-dashboard)
6. [Data Flow](#data-flow)
7. [Deployment](#deployment)

---

## Technology Stack

### **Infrastructure & Messaging**

| Technology | Purpose | Why Chosen |
|-----------|---------|-----------|
| **Docker & Docker Compose** | Container orchestration | Ensures all services run consistently; easy to scale |
| **MQTT (Mosquitto)** | Message broker | Lightweight, publish-subscribe pattern, ideal for IoT |
| **Python 3.11+** | Backend language | Rich ecosystems (FastAPI, ML libraries), fast prototyping |

### **Backend Services**

| Technology | Purpose | Why Chosen |
|-----------|---------|-----------|
| **FastAPI** | REST API framework | Async support, automatic documentation, type safety |
| **Uvicorn** | ASGI server | High performance, handles async operations |
| **Pydantic** | Data validation | Ensures API payloads are correct before processing |
| **aiomqtt / paho-mqtt** | MQTT client | Reliable async/sync MQTT integration |

### **Frontend & UI**

| Technology | Purpose | Why Chosen |
|-----------|---------|-----------|
| **HTML5 / CSS3** | Web interface | Standard, responsive design |
| **Jinja2 Templates** | Dynamic page rendering | Server-side templating, secure |
| **JavaScript (Vanilla)** | Client-side interactivity | No build step needed, direct browser interaction |
| **SQLite** | User authentication database | Lightweight, no external DB needed |

### **Cloud & External Integrations**

| Technology | Purpose | Why Chosen |
|-----------|---------|-----------|
| **ThingSpeak** | Cloud time-series storage | Free tier, IoT-focused, chart visualization |
| **Telegram Bot API** | Push notifications | Reliable, instant delivery, free |

### **Machine Learning**

| Technology | Purpose | Why Chosen |
|-----------|---------|-----------|
| **scikit-learn** | Forecasting models | Proven, lightweight, no GPU needed |
| **pandas / numpy** | Data manipulation | Standard ML stack |

### **Development Tools**

| Technology | Purpose |
|-----------|---------|
| **pytest** | Unit testing |
| **YAML** | Configuration files |
| **JSON** | Data serialization |

---

## Architecture Overview

### **System Diagram**

```
┌──────────────────────────────────────────────────────────────┐
│                    ADMIN USERS                               │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │          WEB DASHBOARD (Port 8501)                      │ │
│  │  - View real-time telemetry                             │ │
│  │  - Set automation targets (policies)                    │ │
│  │  - Monitor decision logs                                │ │
│  │  - Manage users                                         │ │
│  └─────────────┬───────────────────────────────────────────┘ │
│                │                                               │
└────────────────┼───────────────────────────────────────────────┘
                 │
    ┌────────────┴────────────┐
    │                         │
    v                         v
┌─────────────────┐   ┌──────────────────┐
│ CATALOG SERVICE │   │ DECISION SERVICE │
│  (Port 8001)    │   │  (Port 8002)     │
│                 │   │                  │
│ - Room registry │   │ - Policy engine  │
│ - Device list   │   │ - Command logic  │
│ - Policies      │   │ - State machine  │
│ - Conflicts     │   │ - Enforces rules │
│ - Services      │   │                  │
└────────┬────────┘   └──────┬───────────┘
         │                   │
         └───────┬───────────┘
                 │
        ┌────────v──────────┐
        │   MQTT BROKER     │
        │  (Mosquitto)      │
        │  Port 1883        │
        └────────┬──────────┘
                 │
    ┌────────────┼────────────────────┐
    │            │                    │
    v            v                    v
┌─────────┐ ┌──────────────┐  ┌─────────────────┐
│ SENSORS │ │ ADAPTOR API  │  │ TELEGRAM BOT    │
│         │ │ (Port 8000)  │  │ (Background)    │
│ - Temp  │ │              │  │                 │
│ - CO₂   │ │ - ThingSpeak │  │ - Receives      │
│ - Humid │ │   history    │  │   alerts        │
│ - PM2.5 │ │ - Publish    │  │ - Sends msgs    │
│         │ │   to TS      │  │   to users      │
└─────────┘ └──────────────┘  └─────────────────┘
                 │
                 v
         ┌──────────────┐
         │ THINGSPEAK   │
         │ (Cloud)      │
         │              │
         │ - Historical │
         │   data store │
         │ - Charts     │
         └──────────────┘

PREDICTION SERVICE (Port 8003) – Forecast engine
(Consumed by decision service)
```

---

## Core Components

### 1. **Catalog Service** (Port 8001)

**Purpose:** Central registry for rooms, devices, policies, and conflicts.

**Key Endpoints:**
```
GET    /rooms                   → List all rooms
POST   /rooms                   → Create room
GET    /devices                 → List all devices
PUT    /devices/{device_id}     → Update device
GET    /policies                → List policies
POST   /policies                → Create new policy
GET    /conflicts               → List conflict rules
```

**Data Model Example:**
```json
{
  "room_id": "room1",
  "device_ids": ["temp_1", "co2_1", "ac_1"],
  "energy_mode": "NORMAL",
  "schedule": { "weekday": "09:00-18:00", "weekend": "10:00-20:00" }
}
```

**Why It Matters:**
- Single source of truth for device metadata
- Admins define what devices exist and where
- Policies are stored as structured data (metric + operator + threshold + target)

---

### 2. **MQTT Broker** (Mosquitto)

**Purpose:** Real-time message bus connecting all components.

**Why MQTT?**
- **Lightweight**: Low bandwidth for IoT devices
- **Publish-Subscribe**: Decouples producers from consumers
- **QoS levels**: Ensures delivery guarantees
- **Wildcard subscriptions**: Easy topic filtering

**Topic Structure:**
```
airguard/room1/telemetry/sensor/temp_1        → sensor reading
airguard/room1/telemetry/sensor/co2_1         → sensor reading
airguard/room1/telemetry/actuator/ac_1        → actuator status
event/room1/decision_log                      → decision engine output
alert/{room_id}/policy_violation              → alarm trigger
command/{device_id}                           → actuator commands
```

**Example Publish (Sensor):**
```json
Topic: airguard/room1/telemetry/sensor/temp_1
Payload: {
  "device_id": "temp_1",
  "value": 25.3,
  "unit": "°C",
  "timestamp": 1693468800000
}
```

**Example Publish (Decision Engine):**
```json
Topic: event/room1/decision_log
Payload: {
  "room_id": "room1",
  "decisions": [
    {"device_id": "ac_1", "target": "ON", "priority": 2}
  ],
  "commands": [
    {"device_id": "ac_1", "command": "TURN_ON", "target_state": "ON"}
  ],
  "timestamp": 1693468800000
}
```

---

### 3. **Sensor Service** (main_sensor.py)

**Purpose:** Publishes simulated air quality measurements.

**How It Works:**
1. Fetches device list from Catalog Service
2. Runs a sensor driver that generates realistic readings
3. Publishes to MQTT every 5 seconds
4. Incorporates daily trends, actuator influence, and bounded noise

**Sensor Algorithm:**
```python
# Simplified pseudocode
base_value = baseline[metric]  # e.g., 25°C
daily_trend = sin(hour / 24) * amplitude  # Temperature varies by time of day
actuator_effect = -5 if ac_on else 0      # AC cools room
noise = random(-0.5, 0.5)                 # Small jitter
final_value = base_value + daily_trend + actuator_effect + noise
```

**Topics Published:**
- `airguard/room1/telemetry/sensor/{device_id}`

---

### 4. **Decision Service** (Port 8002)

**Purpose:** The "brain" of the system – evaluates policies and issues commands.

**Policy Format:**
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

**How Decision Engine Works:**

```
1. LISTEN: Subscribe to telemetry topics
2. COLLECT: Store latest sensor readings in memory
3. FETCH: Load policies from Catalog Service
4. EVALUATE: For each policy:
   - Check if condition is met (e.g., temp > 26?)
   - If yes, create action candidate
5. SORT: Order candidates by priority (lower = higher priority)
6. FILTER: Apply energy mode rules and conflict resolver
7. STATE_MACHINE: Transition device state (OFF → TURNING_ON → ON)
8. PUBLISH: Send command to MQTT topic
9. LOG: Publish decision log for Telegram/dashboard
```

**State Machine Example:**
```
Current State: OFF
Target State: ON
→ Transition: OFF → TURNING_ON (publish TURN_ON command)
→ Wait for feedback from actuator
→ Feedback: {result: SUCCESS, reported_state: ON}
→ Transition: TURNING_ON → ON (success!)
```

**Commands Published:**
- `command/ac_1` → `{command: "TURN_ON", target_state: "ON"}`
- `event/room1/decision_log` → Full decision summary

---

### 5. **Adaptor Service** (Port 8000)

**Purpose:** Bridge between MQTT and cloud storage (ThingSpeak).

**Two Directions:**

**Ingress (MQTT → Internal):**
- Subscribes to all telemetry topics
- Buffers readings in memory
- Cleans/normalizes data

**Egress (Internal → ThingSpeak):**
- Bulk uploads readings to ThingSpeak every 15 seconds
- Maps MQTT topics to ThingSpeak fields via config.yaml
- Example: `airguard/room1/telemetry/sensor/temp_1` → Field 1

**API Endpoints:**
```
GET /health                                    → Service status
GET /api/v1/history?roomid=room1&starttime=... → Retrieve history
```

**Why ThingSpeak?**
- Free cloud storage for time-series data
- Built-in visualization (charts)
- Perfect for long-term trend analysis
- Public/private channel sharing

---

### 6. **Prediction Service** (Port 8003)

**Purpose:** Forecasts future air quality based on historical data.

**Input:**
- 14–20 days of historical telemetry from ThingSpeak
- Current sensor readings

**Models Used:**
- **ARIMA**: Time-series forecasting
- **Linear Regression**: Trend estimation
- **Exponential Smoothing**: Seasonal patterns

**Output:**
```json
{
  "room_id": "room1",
  "forecast": {
    "temperature": {"value": 27.5, "confidence": 0.85},
    "co2": {"value": 950, "confidence": 0.72}
  },
  "risk_level": "WARNING",  // OK, WARNING, CRITICAL
  "timestamp": 1693468800000
}
```

**Used By:**
- Decision Service (evaluates policies with predictions if available)
- Dashboard (shows forecast cards)

---

### 7. **Dashboard** (Port 8501)

**Purpose:** Web UI for monitoring and administration.

**Key Features:**
1. **Real-time Telemetry Display**
   - Current temp, humidity, CO₂, PM2.5
   - Service health status
   - Device state

2. **Automation Targets Section** ← *Your Main Contribution*
   - Create policies: "If temperature > 30, turn on fan"
   - Edit existing policies
   - Delete policies
   - View all current targets for the room

3. **Decision Log Monitor**
   - What decisions the engine made
   - Which commands were sent
   - Why each decision was made

4. **Admin Panel**
   - Edit environment variables (MQTT credentials, API keys)
   - Create/delete users
   - Reset admin password

5. **Authentication**
   - SQLite-backed login system
   - Admin role can create normal users
   - Session cookies for persistence

**Admin Form Structure (Targets):**
```
Policy ID:     [auto-generated if blank]
Room ID:       [room1]
Metric:        [Temperature ▼] (dropdown: temperature, humidity, co2, pm25)
Operator:      [> ▼] (dropdown: >, <, >=, <=, ==)
Threshold:     [30.0]
Target Device: [ac_1 ▼] (populated from catalog actuators)
Target State:  [ON]
Priority:      [1]

[SAVE] [DELETE]

List of current policies:
  p1: temperature > 26 → ac_1 = ON (priority: 2)
  p2: co2 > 1000 → window_1 = OPEN (priority: 1)
```

---

### 8. **Telegram Notifier** (Background Service)

**Purpose:** Sends real-time alerts to your phone.

**How It Works:**
```
1. Subscribe to MQTT topics:
   - event/{room_id}/decision_log     (what decisions were made)
   - alert/{room_id}/policy_violation  (what alarms triggered)

2. Format message:
   "🚨 ALERT - Room1
    Temperature > 30°C
    Action: Turned on AC_1
    Time: 2026-08-31 14:23:45"

3. Send via Telegram Bot API to your chat
```

**Requires:**
- TELEGRAM_BOT_TOKEN (from BotFather)
- TELEGRAM_CHAT_ID (your personal chat ID)

**Topics Monitored:**
```
event/room1/decision_log
├── Commands: ["turn_on ac_1"]
├── Decisions: [{"device": "ac_1", "state": "ON"}]
└── Energy Mode: NORMAL

alert/room1/policy_violation
├── Policy: "temperature > 26"
├── Current Value: 27.5°C
└── Action: Triggered AC
```

---

## The Alarm System

### **How Alarms Work (End-to-End)**

```
STEP 1: SENSOR READS
┌─────────────────────────────────────────┐
│ Temperature Sensor: 31°C (exceeds 30°C) │
└──────────────┬──────────────────────────┘
               │ Publishes to MQTT
               v
       airguard/room1/telemetry/sensor/temp_1

STEP 2: DECISION ENGINE EVALUATES
┌─────────────────────────────────────────────────────────┐
│ Decision Service receives: temp=31°C                     │
│ Loads policy: IF temperature > 30 THEN turn on fan_1    │
│ Condition: 31 > 30? → TRUE                              │
│ Action: Create command to turn on fan_1                 │
└──────────────┬──────────────────────────────────────────┘
               │ Publishes command to MQTT
               v
        command/fan_1: {command: TURN_ON}

STEP 3: LOGGING DECISION
┌──────────────────────────────────────────────────────┐
│ Publish decision log:                                │
│ event/room1/decision_log {                           │
│   decisions: [{device: fan_1, state: ON}],           │
│   commands: [{device: fan_1, command: TURN_ON}],     │
│   energy_mode: NORMAL                                │
│ }                                                     │
└──────────────┬───────────────────────────────────────┘
               │
        ┌──────┴──────┐
        │             │
        v             v
   TELEGRAM        DASHBOARD
   
STEP 4A: TELEGRAM NOTIFICATION
┌──────────────────────────────────────┐
│ Telegram Notifier receives decision   │
│ Formats message:                      │
│ "🚨 AirGuard Decision                │
│  Room: room1                          │
│  Action: Turn ON fan_1               │
│  Reason: temperature > 30°C          │
│  Time: 14:23:45"                     │
│ Sends to your phone via Telegram Bot │
└──────────────────────────────────────┘

STEP 4B: DASHBOARD UPDATE
┌─────────────────────────────────────────┐
│ Dashboard polls decision log            │
│ Updates "Decision State Store" table:    │
│ Room: room1                             │
│ Device: fan_1                           │
│ State: TURNING_ON → ON                  │
│ Last Action: 2026-08-31 14:23:45        │
└─────────────────────────────────────────┘
```

### **Dual Alert Channels**

| Channel | Delivery | Content | Latency |
|---------|----------|---------|---------|
| **Telegram** | Push notification to phone | Decision summary + reason | ~1–2 seconds |
| **Dashboard** | Web browser (polling) | Detailed decision log + metrics | ~5–10 seconds |

### **Policy Priority System**

When multiple policies trigger, the engine sorts by priority:
```json
[
  {"device": "window_1", "priority": 1},  ← Execute first (CO₂ is most critical)
  {"device": "ac_1", "priority": 2},      ← Execute second
  {"device": "fan_1", "priority": 3}      ← Execute last
]
```

---

## The Webpage Dashboard

### **Architecture: Frontend ↔ Backend**

```
USER BROWSER
  │
  ├─ GET /dashboard                  ← Render main page
  ├─ Jinja2 template rendering       ← Server-side HTML generation
  ├─ CSS styling                     ← Responsive, modern design
  ├─ JavaScript event handlers       ← Click, form submission
  │
  └─ API Calls:
      ├─ POST /admin/targets/create     ← Save new policy
      ├─ POST /admin/targets/{id}/delete ← Remove policy
      ├─ GET /admin/env                 ← Fetch admin page
      ├─ POST /admin/env                ← Update .env file
      │
      └─ Internal Service Calls:
          ├─ GET catalog:8001/policies     ← Fetch current policies
          ├─ GET catalog:8001/devices      ← Fetch room devices
          ├─ GET catalog:8001/room/{id}    ← Fetch room config
          └─ POST catalog:8001/policies    ← Create/update policy
```

### **Your Webpage Contributions**

#### **1. Automation Targets Form**
```html
<section class="card">
  <div class="card-title">
    <span>Automation targets</span>
    <span class="tag">room {{ default_room_id }}</span>
  </div>
  
  <!-- INPUT FORM -->
  <form method="post" action="/admin/targets/create">
    <div class="policy-grid">
      <input name="policy_id" placeholder="Optional, auto-generated" />
      <select name="metric">
        <option value="temperature">temperature</option>
        <option value="co2">co2</option>
        ...
      </select>
      <select name="operator">
        <option value=">">></option>
        <option value="<"><</option>
        ...
      </select>
      <input name="value" type="number" value="30" />
      <select name="target_device">
        <!-- Populated from catalog actuators -->
      </select>
      <input name="target_state" value="ON" />
      <button>Save target policy</button>
    </div>
  </form>
  
  <!-- DISPLAY LIST -->
  {% for policy in room_targets %}
  <div class="policy-row">
    <strong>{{ policy.policy_id }}</strong>
    <span>{{ policy.metric }} {{ policy.operator }} {{ policy.value }}
          → {{ policy.target_device }} = {{ policy.target_state }}</span>
    <button onclick="deletePolicy('{{ policy.policy_id }}')">Delete</button>
  </div>
  {% endfor %}
</section>
```

#### **2. Backend: Policy Creation Handler**
```python
@app.post("/admin/targets/create")
async def admin_create_target(request, room_id, metric, operator, value, ...):
    # Validate inputs
    if operator not in {">", "<", ">=", "<=", "=="}:
        raise HTTPException(status_code=400)
    
    # Create policy payload
    payload = {
        "policy_id": auto_generate_id(),
        "room_id": room_id,
        "metric": metric.lower(),
        "operator": operator,
        "value": float(value),
        "target_device": target_device,
        "target_state": target_state.upper(),
        "priority": priority
    }
    
    # POST to Catalog Service
    response = await http_client.post(
        f"{catalog_url}/policies",
        json=payload
    )
    
    # Redirect with success message
    return redirect("/admin/env?message=Target+saved")
```

#### **3. Device Selector (Auto-Populated)**
```python
# Fetch actuators from catalog
all_devices = await fetch_catalog("/devices")
room_actuators = [
    d for d in all_devices
    if d["room_id"] == "room1" and d["category"] == "actuator"
]

# Pass to template
context["room_devices"] = room_actuators
```

```html
<!-- In template: renders as dropdown -->
<select name="target_device" required>
  {% for device in room_devices %}
    <option value="{{ device.key }}">
      {{ device.name }} ({{ device.device_class }})
    </option>
  {% endfor %}
</select>
```

### **User Workflow in Dashboard**

```
1. ADMIN LOGS IN
   ├─ Username: admin
   └─ Password: password

2. NAVIGATES TO ADMIN PAGE
   └─ Clicks "Back to dashboard" → "Admin env"

3. CREATES AUTOMATION TARGET
   ├─ Fills: metric=temperature, operator=>, value=30
   ├─ Selects: target_device=fan_1, state=ON, priority=1
   └─ Clicks "Save target policy"

4. FORM VALIDATION
   ├─ Checks: operator is valid
   ├─ Checks: value is numeric
   ├─ Checks: device exists in catalog
   └─ Checks: room_id is valid

5. POLICY CREATED
   ├─ Dashboard POSTs to /admin/targets/create
   ├─ Handler validates and calls Catalog Service
   ├─ Catalog Service POST /policies
   ├─ Policy stored in catalog/data/policies.json
   └─ Redirect to /admin/env with "Target saved" message

6. DECISION ENGINE PICKS UP
   ├─ Decision Service periodically fetches policies
   ├─ When temperature > 30°C is detected
   ├─ Sends TURN_ON command to fan_1
   └─ Logs decision to Telegram + Dashboard

7. ADMIN SEES RESULT
   ├─ Dashboard shows: fan_1 state = ON
   ├─ Telegram notification arrives: "Fan turned on"
   └─ Policy list shows the new rule
```

---

## Data Flow

### **Full Cycle Example: Temperature Alert**

```
TIME: 14:20:00
─────────────────────────────────────────────────────────────

SENSOR PUBLISHES (every 5 sec)
  Sensor Driver: temp_1.read() → 27.3°C
  MQTT publish airguard/room1/telemetry/sensor/temp_1
  Payload: {device_id: temp_1, value: 27.3, unit: °C}

ADAPTOR INGESTS
  MQTT ingress listening on airguard/room1/telemetry/sensor/#
  Buffers: temp_1=27.3
  Every 15 sec: bulk POST to ThingSpeak

THINGSPEAK STORES
  Channel: 3319669 (room1 telemetry)
  Field 1 (Temperature): 27.3
  Timestamp: 2026-08-31 14:20:00

─────────────────────────────────────────────────────────────

TIME: 14:20:10
─────────────────────────────────────────────────────────────

DASHBOARD POLLING
  GET /api/thingspeak-rooms
  Returns: latest readings from ThingSpeak
  Browser renders: "Temp 27.3°C" on screen

─────────────────────────────────────────────────────────────

TIME: 14:22:00 (Temperature rises)
─────────────────────────────────────────────────────────────

SENSOR PUBLISHES
  Sensor Driver: temp_1.read() → 31.2°C (exceeds 30°C threshold)
  MQTT publish airguard/room1/telemetry/sensor/temp_1
  Payload: {device_id: temp_1, value: 31.2}

DECISION ENGINE EVALUATES
  Listening to airguard/room1/telemetry/sensor/#
  Receives: temp_1=31.2
  Loads policies from Catalog:
    Policy p1: IF temperature > 30 THEN ac_1 = ON (priority 2)
    Policy p3: IF temperature > 28 THEN fan_1 = ON (priority 3)
  Evaluates both:
    ✓ 31.2 > 30? YES → Create candidate: ac_1 = ON (p=2)
    ✓ 31.2 > 28? YES → Create candidate: fan_1 = ON (p=3)
  Applies energy mode filter
  Sorts by priority: [ac_1 (p=2), fan_1 (p=3)]
  
  STATE MACHINE:
    ac_1 current=OFF, target=ON
    Transition: OFF → TURNING_ON
    Publish: command/ac_1 {command: TURN_ON}
    
    fan_1 current=OFF, target=ON
    Transition: OFF → TURNING_ON
    Publish: command/fan_1 {command: TURN_ON}

PUBLISHES DECISION LOG
  MQTT publish event/room1/decision_log
  Payload:
    {
      room_id: room1,
      decisions: [
        {device: ac_1, state: ON, priority: 2},
        {device: fan_1, state: ON, priority: 3}
      ],
      commands: [
        {device_id: ac_1, command: TURN_ON, target_state: ON},
        {device_id: fan_1, command: TURN_ON, target_state: ON}
      ],
      energy_mode: NORMAL
    }

TELEGRAM NOTIFIER RECEIVES
  Subscribes to: event/room1/decision_log
  Receives decision log
  Formats message:
    "🚨 AirGuard Decision - room1
     Temperature: 31.2°C (> 30°C)
     
     Commands:
     - ac_1: TURN_ON → ON (reason: temperature_>_30)
     - fan_1: TURN_ON → ON (reason: temperature_>_28)
     
     Energy Mode: NORMAL
     Time: 2026-08-31 14:22:00"
  Sends via Telegram Bot API
  YOUR PHONE RECEIVES NOTIFICATION ← Alert!

DASHBOARD UPDATES
  Polling GET /status (decision state store)
  Updates display:
    Room: room1
    Device: ac_1    State: TURNING_ON  Last Action: 14:22:00
    Device: fan_1   State: TURNING_ON  Last Action: 14:22:00

ADAPTOR INGESTS ALL DATA
  Buffers decision log
  Every 15 sec: bulk uploads to ThingSpeak

PREDICTION SERVICE (Optional)
  Runs every 60 sec
  Fetches 14 days history from ThingSpeak
  Builds ARIMA model
  Predicts: "Temp will reach 33°C in 30 minutes"
  Risk Level: WARNING
  Decision Service uses this for lookahead evaluation

─────────────────────────────────────────────────────────────

REPEAT: Sensor continues publishing every 5 seconds
        Dashboard auto-refreshes
        Telegram sends new alerts as policies trigger
```

---

## Deployment

### **Option 1: Docker (Production-Ready)**

```bash
# Clone repository
git clone https://github.com/MateusLanzoni/IoT-AirQualitySystem.git
cd IoT-AirQualitySystem

# Create .env file
cat > .env << EOF
MQTT_USER=iot_admin
MQTT_PASSWORD=airguard2026
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
ADMIN_PASSWORD=your_secure_password
EOF

# Start all services
docker-compose up -d

# Access dashboard
# Browser → http://localhost:8501
# Login → admin / your_secure_password
```

**Services Running:**
- Mosquitto (MQTT): 1883
- Catalog: 8001
- Decision: 8002
- Prediction: 8003
- Adaptor: 8000
- Dashboard: 8501

### **Option 2: Local Python (Development)**

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Terminal 1: MQTT
mosquitto -c mosquitto/config/mosquitto.conf

# Terminal 2: Catalog
cd catalog_service
python -m uvicorn main:app --port 8001

# Terminal 3: Decision
cd decision_service
python -m uvicorn main:app --port 8002

# Terminal 4: Dashboard
cd dashboard_service
python -m uvicorn main:app --port 8501

# Terminal 5: Sensor
python main_sensor.py

# Terminal 6: Adaptor
python main_adaptor.py

# Terminal 7: Telegram (optional)
python telegram_notifier/main.py
```

---

## Key Takeaways for Your Presentation

### **What You Built:**

1. **Automation Target Management (Dashboard)**
   - Form to create/edit/delete policies
   - Auto-populated device selector from catalog
   - Real-time validation and feedback

2. **Decision-to-Telegram Bridge**
   - Modified decision service to include commands in logs
   - Telegram notifier now subscribes to decision logs
   - Users get instant phone alerts

3. **Dual Alert System**
   - **Web Dashboard**: Detailed real-time monitoring
   - **Telegram**: Push notifications to your phone

### **Technologies in Action:**

| Tier | Technology | Role |
|------|-----------|------|
| **Messaging** | MQTT | Decoupled pub-sub communication |
| **Backend** | FastAPI | Type-safe REST APIs |
| **Storage** | SQLite (auth) + JSON (policies) | Lightweight persistence |
| **Frontend** | HTML/CSS/Jinja2 | Responsive web interface |
| **Cloud** | ThingSpeak | Time-series data + charts |
| **Notifications** | Telegram Bot | Push alerts |
| **Orchestration** | Docker Compose | Consistent multi-service deployment |

### **System Properties:**

- ✅ **Scalable**: Add rooms/devices without code changes
- ✅ **Resilient**: Services restart on failure (docker restart policy)
- ✅ **Decoupled**: Components communicate via MQTT, not direct calls
- ✅ **Extensible**: Add new services by subscribing to topics
- ✅ **Automated**: Policies enforce without human intervention
- ✅ **Observable**: Dashboard + Telegram provide visibility

---

## Questions for Discussion

1. How would you handle conflicting policies (e.g., AC wants to cool, window wants to open)?
   - **Answer**: Conflict resolver in decision service + priority sorting

2. What if MQTT broker goes down?
   - **Answer**: Docker restart policy + persistent volumes for message buffering

3. How do predictions improve decision-making?
   - **Answer**: Lookahead evaluation (prevent overheating before it happens)

4. Can you add new sensor types?
   - **Answer**: Yes! Register in Catalog, sensor driver reads from config, policy engine handles it

5. How does the system scale to 100 rooms?
   - **Answer**: Each room has independent policies; MQTT broker handles all subscriptions efficiently

---

## Conclusion

The **IoT Air Quality System** demonstrates:
- **Distributed microservices** architecture (Catalog, Decision, Prediction)
- **Real-time IoT messaging** via MQTT
- **Cloud integration** for historical analysis
- **Instant notifications** via Telegram
- **Web-based administration** via Flask/Jinja2 dashboard
- **Automated enforcement** of user-defined policies

**Your contribution** integrated the admin UI with the decision pipeline, creating an end-to-end alarm system that notifies users instantly on their phone when air quality thresholds are exceeded.

---

*For questions or live demonstration, refer to the GitHub repository and QUICKSTART guide.*
