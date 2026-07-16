# Quick Start Guide – IoT Air Quality System

## Prerequisites

- **Git** installed
- **Docker & Docker Compose** (for containerized setup) OR **Python 3.11+** (for local setup)
- **MQTT Broker** (Mosquitto, included in docker-compose)
- **Telegram Bot** (optional, for alerts)

---

## Option 1: Docker Compose (Recommended)

### Step 1: Clone the Repository
```bash
git clone https://github.com/MateusLanzoni/IoT-AirQualitySystem.git
cd IoT-AirQualitySystem
```

### Step 2: Create Environment File
Create a `.env` file in the project root:
```bash
cp .env.example .env  # if template exists, or create manually
```

Or manually create `.env`:
```env
# MQTT Configuration
MQTT_USER=iot_admin
MQTT_PASSWORD=airguard2026
MQTT_PORT=1883
MQTT_BROKER=mosquitto

# Optional: ThingSpeak Integration
THINGSPEAK_WRITE_API_KEY=your_write_key
THINGSPEAK_READ_API_KEY=your_read_key
THINGSPEAK_COMMAND_WRITE_API_KEY=your_command_key

# Optional: Telegram Alerts
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_BOT_NAME=AirGuard Alerts

# Admin Credentials
ADMIN_PASSWORD=password
ADMIN_USERNAME=admin

# History Lookback (for prediction service)
HISTORY_LOOKBACK_DAYS=20

# Optional: Turin Outdoor AQI
OUTDOOR_AQI_TOKEN=
```

### Step 3: Start Services
```bash
docker-compose up -d
```

This starts:
- **MQTT Broker** (Mosquitto) → `mqtt://localhost:1883`
- **Catalog Service** → `http://localhost:8001`
- **Prediction Service** → `http://localhost:8003`
- **Decision Service** → `http://localhost:8002`
- **Adaptor Service** → `http://localhost:8000`
- **Dashboard** → `http://localhost:8501`
- **Telegram Notifier** (background)
- **Sensor Service** (background)

### Step 4: Access the Dashboard
1. Open browser → `http://localhost:8501`
2. Login with:
   - Username: `admin`
   - Password: `password` (or your ADMIN_PASSWORD)

### Step 5: Define Automation Targets (Admin Page)
1. Click **"Admin env"** link on dashboard
2. Navigate to **"Automation targets"** section
3. Create targets like:
   - **If temperature > 30°C → turn on fan**
   - **If CO₂ > 1000 ppm → open window**
4. Save targets → Decision service will enforce them

### Step 6: Monitor Decisions
- Check **Decision state store** tab to see active commands
- Telegram alerts will fire when targets are triggered (if configured)

### Stop Services
```bash
docker-compose down
```

---

## Option 2: Local Setup (Python)

### Step 1: Clone Repository
```bash
git clone https://github.com/MateusLanzoni/IoT-AirQualitySystem.git
cd IoT-AirQualitySystem
```

### Step 2: Create Virtual Environment
```bash
# Windows
python -m venv .venv
.\.venv\Scripts\activate

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Create `.env` File
Same as Option 1 (see above)

### Step 5: Start MQTT Broker Separately
```bash
# If you have Mosquitto installed locally
mosquitto -c mosquitto/config/mosquitto.conf

# OR use Docker just for MQTT
docker run -d -p 1883:1883 -p 9001:9001 --name mosquitto eclipse-mosquitto:2.0
```

### Step 6: Start Each Service

**Terminal 1 - Catalog Service**
```bash
cd catalog_service
..\.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8001
```

**Terminal 2 - Adaptor Service**
```bash
python main_adaptor.py
```

**Terminal 3 - Sensor Service** (publishes mock data)
```bash
python main_sensor.py
```

**Terminal 4 - Prediction Service**
```bash
cd services/prediction
..\..\.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8003
```

**Terminal 5 - Decision Service**
```bash
cd decision_service
..\..\.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002
```

**Terminal 6 - Dashboard**
```bash
cd dashboard_service
..\..\.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8501
```

**Terminal 7 - Telegram Notifier** (optional)
```bash
python telegram_notifier/main.py
```

### Step 7: Access Dashboard
- Browser → `http://localhost:8501`
- Login: `admin` / `password`

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Dashboard (8501)                      │
│              - Admin target setup                        │
│              - System monitoring                         │
│              - User & room management                    │
└────────────────┬────────────────────────────────────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    v            v            v
 Catalog    Adaptor     Decision  
 (8001)     (8000)       (8002)
    │            │            │
    │       MQTT Broker       │
    │      (mosquitto)        │
    │            │            │
    ├────────────┼────────────┤
    │            │            │
    v            v            v
 Sensors   ThingSpeak    Policy Engine
         (History)      (Enforcement)
                             │
                             v
                     Telegram Notifier
                      (Alerts & Logs)
```

---

## Troubleshooting

### Dashboard won't load
```bash
# Check if port 8501 is in use
netstat -tuln | grep 8501  # Linux/macOS
netstat -ano | findstr :8501  # Windows
```

### Can't connect to MQTT
- Verify Mosquitto is running: `mosquitto -v` in terminal
- Check MQTT_BROKER and MQTT_PORT in `.env`
- Test connection: `mosquitto_sub -h localhost -t test`

### Sensor data not appearing
- Check sensor service is running: `python main_sensor.py`
- Verify MQTT connection: topics should publish to `airguard/room_1/telemetry/device/*`

### No Telegram notifications
- Verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in `.env`
- Check telegram_notifier service is running
- Monitor MQTT topic: `mosquitto_sub -h localhost -t "alert/#"`

### Permission issues
```bash
# Clear Python cache
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

---

## Key Endpoints

| Service | URL | Purpose |
|---------|-----|---------|
| Dashboard | `http://localhost:8501` | Web UI |
| Catalog | `http://localhost:8001/docs` | Room & device registry |
| Adaptor | `http://localhost:8000/docs` | ThingSpeak history |
| Prediction | `http://localhost:8003/docs` | IAQ forecasting |
| Decision | `http://localhost:8002/docs` | Policy engine |
| MQTT | `mqtt://localhost:1883` | Message broker |

---

## Next Steps

1. **Set up your room** → Create room in Catalog
2. **Add devices** → Register sensors (temp, CO₂, humidity) and actuators (AC, fan, window)
3. **Create targets** → Admin page → automation targets
4. **Configure Telegram** (optional) → Add bot token + chat ID
5. **Run sensors** → Main sensor service publishes mock data automatically
6. **Monitor decisions** → Watch dashboard decision log in real-time

---

## Configuration Reference

### Environment Variables

```env
# Server
SERVER_HOST=0.0.0.0  # Listen on all interfaces
ADMIN_PASSWORD=password
ADMIN_USERNAME=admin

# MQTT
MQTT_BROKER=mosquitto  # hostname or IP
MQTT_PORT=1883
MQTT_USER=iot_admin
MQTT_PASSWORD=airguard2026

# Service URLs (for container networking)
CATALOG_SERVICE_URL=http://catalog-service:8001
PREDICTION_SERVICE_URL=http://prediction-service:8003
DECISION_SERVICE_URL=http://decision-service:8002
ADAPTOR_SERVICE_URL=http://adaptor-service:8000

# ThingSpeak (optional)
THINGSPEAK_WRITE_API_KEY=
THINGSPEAK_READ_API_KEY=
THINGSPEAK_COMMAND_WRITE_API_KEY=

# Telegram (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_BOT_NAME=AirGuard Alerts

# Prediction
HISTORY_LOOKBACK_DAYS=20
OUTDOOR_AQI_TOKEN=

# Paths
DEFAULT_ROOM_ID=room1
ROOT_ENV_PATH=./.env
ADAPTOR_CONFIG_PATH=./components/adaptor/config.yaml
```

---

## Default Credentials

- **Admin Dashboard**
  - Username: `admin`
  - Password: `password`

- **MQTT Broker**
  - User: `iot_admin`
  - Password: `airguard2026`

⚠️ **Change these in production!**

---

## Support

- Check **README.md** for architecture details
- Review **docker-compose.yml** for service configuration
- Inspect **decision_service/config.yaml** for policy engine settings
- See **catalog_service/data/** for sample room/device/policy data

