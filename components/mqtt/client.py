import os
import time
import json
import asyncio
import logging
import aiomqtt
from pydantic import ValidationError

from core.event_bus import EventBus
from components.mqtt.const import (
    EVENT_STATE_CHANGED,
    EVENT_COMMAND_RECEIVED,
    TOPIC_TELEMETRY,
    TOPIC_COMMAND_ALL_ROOMS
)
from components.mqtt.schemas import TelemetryMessage, CommandMessage

_LOGGER = logging.getLogger(__name__)

class MQTTGateway:
    """
    The bilateral bridge between MQTT and the internal Event Bus.
    """
    def __init__(self, bus:EventBus):
        self.bus = bus
        self.client = None
        self.broker = os.getenv("MQTT_BROKER", "localhost")

    async def start(self):
        """Starts the gateway, connect to broker, and runs listener loops."""

        # Register to listen to the internal bus
        self.bus.async_listen(EVENT_STATE_CHANGED, self._on_state_changed)
        _LOGGER.info(f"Connected to internal bus at {self.broker}")

        # Connect to mosquitto (external MQTT broker)
        try:
            async with aiomqtt.Client(
                hostname=self.broker
            ) as client:
                self.client = client
                _LOGGER.info(f"Connected to MQTT Broker at {self.broker}")

                # Start listening to command topic
                await self._listen_to_commands()
        
        except aiomqtt.MqttError as e:
            _LOGGER.error(f"Mosquitto connection error: {e}")
            # Retry logic placeholder(for now I didn't implement)

        except Exception as e:
            _LOGGER.error(f"Error in MQTT Gateway: {e}")
    
    # Outbound flow: internal event bus -> mosquitto( external )
    async def _on_state_changed(self, event):
        """Triggered when a sensor or actuator changes state."""

        if not self.client:
            return
        
        try:
            # extract roome_id from event data
            room_id = event.data.get("room_id")
            if not room_id:
                _LOGGER.warning("Missing 'room_id'.")
                return

            device_type = event.data.get("device_type", "sensor")

            raw_payload = {
                "device_id": event.data["device_id"],
                "value": event.data["value"],
                "timestamp": int(time.time())
            }

            # Data validation using schema.py
            validated_msg = TelemetryMessage(**raw_payload)

            topic = TOPIC_TELEMETRY.format(
                room_id = room_id,
                device_type = device_type,
                device_id=validated_msg.device_id
            )

            # Fire and forget(don't wait)
            await self.client.publish(topic, payload=validated_msg.model_dump_json())
            _LOGGER.debug(f"Published: {topic} to {validated_msg.model_dump_json()}")

        except ValidationError as e:
            _LOGGER.error(f"Schema validation error: {e}")
        except Exception as e:
            _LOGGER.error(f"Failed to Publish: {e}")

    # Inbound flow: mosquitto( external ) -> internal event bus
    async def _listen_to_commands(self):
        """Listen to incoming commands and routes them to event bus."""

        command_topic_patterns = [TOPIC_COMMAND_ALL_ROOMS, "control/#"]
        for command_topic_pattern in command_topic_patterns:
            await self.client.subscribe(command_topic_pattern)
            _LOGGER.info(f"Subscribed to wildcard command topic: {command_topic_pattern}")

        async for message in self.client.messages:
            try:
                # Supported topic structures:
                #   airguard/{room_id}/command/{device_type}/{device_id}
                #   control/{room_id}/{device_id}/command
                topic_str = str(message.topic)
                segments = topic_str.split('/')

                extracted_room_id = None
                extracted_device_type = None

                if len(segments) >= 5 and segments[0] == "airguard" and segments[2] == "command":
                    extracted_room_id = segments[1]
                    extracted_device_type = segments[3]
                elif len(segments) >= 4 and segments[0] == "control" and segments[3] == "command":
                    extracted_room_id = segments[1]
                    extracted_device_type = None
                else:
                    continue

                payload_str = message.payload.decode()
                raw_data = json.loads(payload_str)

                validated_cmd = CommandMessage(**raw_data)
                cmd_dict = validated_cmd.model_dump()

                # Attach extracted context to event data before routing to internal bus
                cmd_dict["room_id"] = extracted_room_id
                cmd_dict["device_type"] = extracted_device_type or cmd_dict.get("device_type") or "actuator"

                _LOGGER.info(
                    f"Received command for Room: {extracted_room_id}, "
                    f"Device: {validated_cmd.device_id}, Action: {validated_cmd.action}"
                )

                await self.bus.async_fire(EVENT_COMMAND_RECEIVED, cmd_dict)

            except json.JSONDecodeError:
                _LOGGER.warning(f"Wrong formed JSON:{message.topic.value}")
            except ValidationError as e:
                _LOGGER.warning(f"Schema validation error: {e}")
            except Exception as e:
                _LOGGER.error(f"Error processing command: {e}")



