"""
MQTT Ingress Client for ThingSpeak Adaptor Component.
Acts as a Consumer : Listens to MQTT topics and updates the internal state buffer.
"""
import asyncio
import json
import logging
import aiomqtt

from .buffer import buffer_instance

logger = logging.getLogger(__name__)

async def start_ingress(broker_host: str, port: int, topic_to_subscribe: list) -> None:
    """
    Connects to broker, subscribes to configured topics,
    pushes data to the state buffer."""

    reconnect_interval = 5 # seconds
    while True:
        try:
            logger.info(f"Connecting to MQTT broker at {broker_host}:{port}") 

            # Use async context manager to handle connection
            async with aiomqtt.Client(hostname=broker_host, port=port) as client:

                # Subscribe only to topics in config.yaml
                for topic in topic_to_subscribe:
                    await client.subscribe(topic)
                    logger.debug(f"Subscribed to topic: {topic}")

                logger.info("Ingress client is listening for msgs.")

                # Async generator to process messages without blocking
                async for message in client.messages:
                    process_message(message)
        except aiomqtt.MqttError as error:
            logger.error(f"MQTT connection error: {error}. Retrying in {reconnect_interval} seconds...")
            await asyncio.sleep(reconnect_interval)
        except Exception as e:
            logger.critical(f"Unexpected error in MQTT Ingress Client: {e}. ")
            await asyncio.sleep(reconnect_interval)

def process_message(message: aiomqtt.Message)-> None:
    """
    Decode the MQTT msgs and updates the buffer
    """
    topic = str(message.topic)

    try:
        # Decode payload
        raw_payload = message.payload.decode('utf-8')
        final_value = None

        # Attempt to parse as JSON
        # Expected: {"device_id": "temp_1", "value": 26.72, "unit": "°C"}
        try:
            parsed_data = json.loads(raw_payload)
            if isinstance(parsed_data, dict) and "value" in parsed_data:
                final_value = parsed_data["value"]
            else:
                final_value = parsed_data
        
        # Fallback to plain text parsing(actuator)
        # Expected: "ON" or "OFF"
        except json.JSONDecodeError:
            clean_text = raw_payload.strip().upper()
            if clean_text == "ON":
                final_value = 1
            elif clean_text == "OFF":
                final_value = 0
            else:
                final_value = raw_payload
        
        # Update the buffer 
        if final_value is not None:
            buffer_instance.push_event(topic, final_value)
            logger.debug(f"event queued: {topic} -> {final_value}")
    
    except Exception as e:
        logger.error(f"Error processing MQTT message on topic {topic}: {e}")



