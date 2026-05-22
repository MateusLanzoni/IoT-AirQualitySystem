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
    TOPIC_PREFIX
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
            raw_payload = {
                "device_id": event.data["device_id"],
                "value": event.data["value"],
                "timestamp": int(time.time())
            }

            # Data validation using schema.py
            validated_msg = TelemetryMessage(**raw_payload)

            topic = TOPIC_TELEMETRY.format(
                device_type="device",
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

        # Subscribe to all commands targeting this device
        command_topic_pattern = "control/#"
        await self.client.subscribe(command_topic_pattern)

        # Listening loop
        async for message in self.client.messages:
            try:
                # Decode payload to string, then parse JSON
                payload_str = message.payload.decode()
                raw_data = json.loads(payload_str)

                # Schema validation
                # If a service sends wrong JSON (e.g. action="explode"), this will throw ValidationError
                validated_cmd = CommandMessage(**raw_data)

                _LOGGER.info(f"Received command for {validated_cmd.device_id}:{validated_cmd.action}")

                # Route to event bus
                # This will NOT excute the command, only pass the dict to bus.
                await self.bus.async_fire(
                    EVENT_COMMAND_RECEIVED,
                    validated_cmd.model_dump() 
                )
            
            except json.JSONDecodeError:
                _LOGGER.warning(f"Wrong formed JSON:{message.topic.value}")
            except ValidationError as e:
                _LOGGER.warning(f"Schema validation error: {e}")
            except Exception as e:
                _LOGGER.error(f"Error processing command: {e}")



