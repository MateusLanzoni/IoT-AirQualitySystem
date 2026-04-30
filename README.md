# Quickstart
```bash
 # Catalog Service
  cd catalog_service
  pip install -r requirements.txt
  python main.py           # port :8001

  # Decision Service
  cd decision_service
  pip install -r requirements.txt
  python main.py           # port :8002
```
--- 

# structure
## catalog_service
```text
📦catalog_service
 ┣ 📂data
 ┃ ┣ 📜conflicts.json
 ┃ ┣ 📜devices.json
 ┃ ┣ 📜policies.json
 ┃ ┣ 📜rooms.json
 ┃ ┗ 📜services.json
 ┣ 📜config.yaml
 ┣ 📜main.py
 ┣ 📜requirements.txt
 ┣ 📜routers.py
 ┣ 📜scheduler.py
 ┣ 📜schemas.py
 ┗ 📜storage.py
``` 

## decision_service
```text
📦decision_service
 ┣ 📂data
 ┃ ┗ 📜mock_sensor_event.json
 ┣ 📜config.yaml
 ┣ 📜conflict_resolver.py
 ┣ 📜energy_mode.py
 ┣ 📜main.py
 ┣ 📜mqtt_handler.py
 ┣ 📜policy_engine.py
 ┣ 📜processor.py
 ┣ 📜requirements.txt
 ┣ 📜state_machine.py
 ┗ 📜state_store.py
```

## Key Design Decisions

| Area               | Catalog Service                                              | Decision Service                                      |
|--------------------|--------------------------------------------------------------|--------------------------------------------------------|
| Storage            | In-memory dict (indexed map) + JSON write-through            | In-memory StateStore (thread-safe)                    |
| Scheduling         | asyncio background tasks (heartbeat + health check)          | paho-mqtt thread + asyncio.Queue decoupling           |
| ThingSpeak         | mock_mode: true for random data, disable in config to use real API | —                                              |
| MQTT Unavailable   | —                                                            | Automatically falls back to _DummyPublisher with logging |
| Config             | config.yaml centralizes all parameters, loaded once at startup | Same as left                                          |

## mockup
- test Decision Service (no MQTT)
triggered decision process by mock_sensor_event.json
```bash
curl -X POST http://localhost:8002/trigger/room1 \
-H "Content-Type: application/json" \
-d @decision_service/data/mock_sensor_event.json
```

## check device status
```bash
curl http://localhost:8002/status
```