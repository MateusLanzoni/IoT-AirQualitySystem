from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("telegram_notifier")


MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_ALERT_TOPIC = os.getenv("MQTT_ALERT_TOPIC", "alert/#")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_BOT_NAME = os.getenv("TELEGRAM_BOT_NAME", "AirGuard Alerts")


def _format_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    try:
        raw = int(value)
    except Exception:
        return str(value)
    if raw > 10_000_000_000:
        raw = raw / 1000
    return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _format_alert(topic: str, payload: dict[str, Any]) -> str:
    room_id = payload.get("room_id")
    if not room_id and topic.startswith("alert/"):
        parts = topic.split("/")
        room_id = parts[1] if len(parts) > 1 else "unknown"

    alert_type = payload.get("type", "alert")
    device_id = payload.get("device_id", "unknown")
    message = payload.get("message", "")
    timestamp = _format_timestamp(payload.get("timestamp"))

    lines = [
        f"{TELEGRAM_BOT_NAME}",
        f"Room: {room_id or 'unknown'}",
        f"Type: {alert_type}",
        f"Device: {device_id}",
        f"Time: {timestamp}",
    ]
    if message:
        lines.append(f"Message: {message}")
    return "\n".join(lines)


def _send_telegram_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials missing; alert will be logged only.")
        logger.info(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=10,
    )
    response.raise_for_status()


def _on_connect(client, userdata, flags, rc):
    if rc != 0:
        logger.error("MQTT connect failed rc=%s", rc)
        return
    client.subscribe(MQTT_ALERT_TOPIC)
    logger.info("Subscribed to %s", MQTT_ALERT_TOPIC)


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        logger.warning("Dropped non-JSON alert on %s", msg.topic)
        return

    try:
        text = _format_alert(str(msg.topic), payload if isinstance(payload, dict) else {})
        _send_telegram_message(text)
        logger.info("Alert forwarded from %s", msg.topic)
    except Exception as exc:
        logger.error("Failed to forward alert from %s: %s", msg.topic, exc)


def main() -> None:
    client = mqtt.Client(client_id="telegram_notifier")
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    logger.info("Connecting to MQTT broker %s:%s", MQTT_BROKER, MQTT_PORT)
    client.loop_forever()


if __name__ == "__main__":
    main()