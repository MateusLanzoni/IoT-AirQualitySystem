1. Mosquitto 2.0.0 Connection Credentials
Host: airguard-mosquitto (Use localhost if connecting from outside the Docker network)
Port: 1883
Username: iot_admin
Password: airguard2026

2. MQTT Topic Architecture
The project strictly follows a hierarchical topic structure for bidirectional communication:

Telemetry (Upstream - Sensor to Cloud):
Format: airguard/telemetry/{room_id}/{device_type}/{device_id}
Example: airguard/telemetry/livingroom/sensor/temp_01
Payload: JSON containing device_id, value, and timestamp.

Command (Downstream - Cloud to Actuator):
Format: airguard/command/{room_id}/{device_id}
Example: airguard/command/livingroom/ac_01
Payload: JSON containing device_id and action (e.g., turn_on, turn_off).

3. Example: publish a telemetry message (Upstream)
            telemetry_topic = "airguard/telemetry/livingroom/sensor/temp_01"
            payload = json.dumps({
                "device_id": "temp_01",
                "value": 25.5,
                "timestamp": 1712650000
            })
            await client.publish(telemetry_topic, payload=payload)
