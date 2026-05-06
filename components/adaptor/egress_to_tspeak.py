"""
thingspeak egress, pulls from buffer,
transforms topics via config, bulk uploads via HTTPX
"""
import httpx
import logging
import asyncio
from typing import Dict, Any, List
from .buffer import buffer_instance

logger = logging.getLogger(__name__)

TS_BULK_URL = "https://api.thingspeak.com/channels/{channel_id}/bulk_update.json"

async def start_egress(config: Dict[str, Any]) -> None:
    """
    Initializes the routing table and starts the persistent background loop
    """
    interval = config.get("global", {}).get("update_interval_seconds", 15)
    channels = config.get("channels", [])

    # routing table: topic -> (channel_id, field_id)
    # Format {"sensor/temp_01": ("3319669", "NMJ74...", "field2"), }
    routing_table = {}
    for ch in channels:
        ch_id = str(ch["channel_id"])
        api_key = ch["write_api_key"]
        fields = ch.get("fields", {})  # this is the defined mapping of thingspeak
        for field_name, topic in fields.items():
            if topic is not None:

                # mapping topic to channel, field(field1, field2, etc)
                routing_table[topic] = (ch_id, api_key, field_name)

    logger.info(f"Egress initialized with {len(routing_table)} topics")

    # Start httpx client session
    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            await asyncio.sleep(interval)
            await _process_and_send(client, routing_table)

async def _process_and_send(client: httpx.AsyncClient, routing_table: Dict[str, Any]) -> None:
    """
    Drains the buffer, Groups by channel ID, fires HTTP POST requests.
    """
    # Drain the fuffer
    raw_events = buffer_instance.drain_all()
    if not raw_events:
        return
    
    # Group events by channel ID based on the routing table
    payloads_by_channel = {}

    for event in raw_events:
        topic = event["topic"]

        if topic not in routing_table:
            continue  # No mapping for this topic, skip it

        ch_id, api_key, field_name = routing_table[topic]

        # Initialize payload
        if ch_id not in payloads_by_channel:
            payloads_by_channel[ch_id] ={
                "write_api_key": api_key,
                "updates": []
            }
        # Append the new update to the channel's payload
        payloads_by_channel[ch_id]["updates"].append(
            {
                "created_at": event["timestamp"],
                field_name: event["value"]
            }
        )
    
    # Send bulk updates for each channel
    tasks = []
    for ch_id, payload in payloads_by_channel.items():
        url = TS_BULK_URL.format(channel_id=ch_id)
        # Post tasks 
        tasks.append(_post_to_thingspeak(client, url, ch_id, payload))

    # Await all post tasks to complete
    if tasks:
        await asyncio.gather(*tasks)

async def _post_to_thingspeak(client: httpx.AsyncClient, url: str, ch_id: str, payload: Dict[str, Any]) -> None:
    """
    Excutes the HTTP POST request to ThingSpeak.
    """
    try:
        response = await client.post(url, json=payload)

        # Thingspeak returns 202 for successful bulk updates
        if response.status_code == 202:
            logger.info(f"Successfully posted to channel {ch_id} with {len(payload['updates'])} updates.")
        else:
            logger.error(f"Failed to post to channel {ch_id}. Status: {response.status_code}, Response: {response.text}")
    
    except Exception as e:
        logger.error(f"Error posting to channel {ch_id}: {e}")