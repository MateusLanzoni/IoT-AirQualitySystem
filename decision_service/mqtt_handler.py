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
        topic = f"control/{room_id}/{device_id}/command"
        self._publish(topic, cmd)

    def publish_alert(self, room_id: str, alert_type: str, device_id: str, message: str):
        topic = f"alert/{room_id}"
        self._publish(topic, {
            "type": alert_type,
            "device_id": device_id,
            "message": message,
            "timestamp": int(time.time() * 1000),
        })

    def publish_decision_log(self, room_id: str, decisions: list, filtered: list, energy_mode: str):
        topic = f"event/{room_id}/decision_log"
        self._publish(topic, {
            "room_id": room_id,
            "decisions": decisions,
            "filtered_actions": filtered,
            "energy_mode": energy_mode,
            "timestamp": int(time.time() * 1000),
        })


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
            client.subscribe(cfg["topic_sensor"])
            client.subscribe(cfg["topic_device_status"])
            logger.info(f"Subscribed: {cfg['topic_sensor']}, {cfg['topic_device_status']}")
        else:
            logger.error(f"MQTT connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"MQTT disconnected rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            asyncio.run_coroutine_threadsafe(
                self._queue.put((msg.topic, payload)),
                self._loop,
            )
        except Exception as e:
            logger.error(f"Failed to parse MQTT message [{msg.topic}]: {e}")
