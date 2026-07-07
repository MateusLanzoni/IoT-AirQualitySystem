"""
MQTT client wrapper (paho-mqtt).

Subscriber: sensor state + device feedback topics
Publisher:  control commands, alerts, decision logs

Integration with asyncio:
  MQTT callbacks run in paho's background thread.
  Messages are pushed into an asyncio.Queue via run_coroutine_threadsafe.
"""
import asyncio
import json
import logging
import time
from typing import Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTPublisher:
    def __init__(self, client: mqtt.Client):
        self._client = client

    def _publish(self, topic: str, payload: dict):
        try:
            self._client.publish(topic, json.dumps(payload), qos=1)
        except Exception as e:
            logger.error(f"MQTT publish failed [{topic}]: {e}")

    def publish_command(self, room_id: str, device_id: str, cmd: dict):
        topic = f"airguard/{room_id}/command/device/{device_id}"
        command = str(cmd.get("command", "")).upper()
        action = "set_value"
        if command == "TURN_ON":
            action = "turn_on"
        elif command == "TURN_OFF":
            action = "turn_off"

        payload = {
            "device_id": device_id,
            "action": action,
        }
        params = cmd.get("params")
        if isinstance(params, dict) and params:
            payload["params"] = params

        self._publish(topic, payload)

    def publish_alert(self, room_id: str, alert_type: str, device_id: str, message: str):
        topic = f"alert/{room_id}"
        self._publish(topic, {
            "type": alert_type,
            "device_id": device_id,
            "message": message,
            "timestamp": int(time.time() * 1000),
        })

    def publish_decision_log(self, room_id: str, decisions: list, filtered: list, energy_mode: str, commands: list | None = None):
        topic = f"event/{room_id}/decision_log"
        payload = {
            "room_id": room_id,
            "decisions": decisions,
            "filtered_actions": filtered,
            "energy_mode": energy_mode,
            "timestamp": int(time.time() * 1000),
        }
        if commands is not None:
            payload["commands"] = commands
        self._publish(topic, payload)


class MQTTHandler:
    def __init__(self, config: dict, event_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self._config = config
        self._queue = event_queue
        self._loop = loop
        self._client: Optional[mqtt.Client] = None

    def start(self) -> MQTTPublisher:
        cfg = self._config["mqtt"]
        client = mqtt.Client(client_id=cfg["client_id"])
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        client.connect(cfg["broker"], cfg["port"], keepalive=cfg.get("keepalive", 60))
        client.loop_start()
        self._client = client
        return MQTTPublisher(client)

    def stop(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT connected")
            cfg = self._config["mqtt"]
            sensor_topics = cfg.get("topic_sensor", [])
            if isinstance(sensor_topics, str):
                sensor_topics = [sensor_topics]
            if "airguard/+/telemetry/#" not in sensor_topics:
                sensor_topics.append("airguard/+/telemetry/#")

            for topic in sensor_topics:
                client.subscribe(topic)
            client.subscribe(cfg["topic_device_status"])
            logger.info(f"Subscribed sensor topics: {sensor_topics}")
            logger.info(f"Subscribed status topic: {cfg['topic_device_status']}")
        else:
            logger.error(f"MQTT connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"MQTT disconnected rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            topic = str(msg.topic)
            payload = json.loads(msg.payload.decode("utf-8"))

            if topic.startswith("airguard/"):
                normalized = self._normalize_airguard_telemetry(topic, payload)
                if normalized is None:
                    return
                topic, payload = normalized

            asyncio.run_coroutine_threadsafe(
                self._queue.put((topic, payload)),
                self._loop,
            )
        except Exception as e:
            logger.error(f"Failed to parse MQTT message [{msg.topic}]: {e}")

    def _normalize_airguard_telemetry(self, topic: str, payload: dict) -> Optional[tuple]:
        if not isinstance(payload, dict):
            return None

        parts = topic.split("/")
        if len(parts) < 5 or parts[2] != "telemetry":
            return None

        room_id = parts[1]
        device_id = parts[4]
        metric = self._metric_from_device_id(device_id)
        value = payload.get("value")
        if metric is None or value is None:
            return None

        ts = payload.get("timestamp", int(time.time() * 1000))
        try:
            ts = int(ts)
        except Exception:
            ts = int(time.time() * 1000)
        if ts < 10_000_000_000:
            ts *= 1000

        normalized_topic = f"sensor/{room_id}/state"
        normalized_payload = {
            "room_id": room_id,
            "timestamp": ts,
            "metrics": {metric: value},
            "meta": {
                "device_id": device_id,
                "source_topic": topic,
            },
        }
        return normalized_topic, normalized_payload

    @staticmethod
    def _metric_from_device_id(device_id: str) -> Optional[str]:
        prefix = device_id.split("_", 1)[0].lower()
        mapping = {
            "temp": "temperature",
            "temperature": "temperature",
            "humi": "humidity",
            "humidity": "humidity",
            "co2": "co2",
            "pm25": "pm25",
            "aqi": "aqi",
        }
        return mapping.get(prefix)
