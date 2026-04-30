# quickstart
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

## Key Design Decisions
## Key Design Decisions

| Area               | Catalog Service                                              | Decision Service                                      |
|--------------------|--------------------------------------------------------------|--------------------------------------------------------|
| Storage            | In-memory dict (indexed map) + JSON write-through            | In-memory StateStore (thread-safe)                    |
| Scheduling         | asyncio background tasks (heartbeat + health check)          | paho-mqtt thread + asyncio.Queue decoupling           |
| ThingSpeak         | mock_mode: true for random data, disable in config to use real API | —                                              |
| MQTT Unavailable   | —                                                            | Automatically falls back to _DummyPublisher with logging |
| Config             | config.yaml centralizes all parameters, loaded once at startup | Same as left                                          |

---

# triggered decision process by mock_sensor_event.json 
test Decision Service (no MQTT)
```bash
curl -X POST http://localhost:8002/trigger/room1 \
-H "Content-Type: application/json" \
-d @decision_service/data/mock_sensor_event.json
```

# check device status
```bash
curl http://localhost:8002/status
```