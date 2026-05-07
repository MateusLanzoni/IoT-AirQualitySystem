"""
thingspeak egress, pulls from buffer,
transforms topics via config, bulk uploads via HTTPX
"""
import httpx
import logging
import asyncio
from typing import Dict, Any
from .buffer import buffer_instance

logger = logging.getLogger(__name__)

TS_BULK_URL = "https://api.thingspeak.com/channels/{channel_id}/bulk_update.json"


def _extract_room_id_from_topic(topic: str) -> str | None:
    """Extract room_id from topic pattern: airguard/<room_id>/..."""
    parts = topic.split("/")
    if len(parts) >= 2 and parts[0] == "airguard":
        return parts[1]
    return None

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
    thingspeak standard bulk update format:
        {
        "write_api_key": "YOUR_KEY",
        "updates": [
                    {
                    "created_at": "2026-05-07T00:35:04Z", 
                    "field1": 22.54, 
                    "field2": 614.02, 
                    "field3": 49.88, 
                    ...
                    }
                    ]
        }
    """
    # Drain the fuffer
    raw_events = buffer_instance.drain_all()
    if not raw_events:
        return
    
    # Group events by channel ID based on the routing table
    payloads_by_channel = {}
    nested_dict = {} # Temporary nested dict to hold intermediate data before transforming to ThingSpeak's expected format

    for event in raw_events:
        topic = event["topic"]

        if topic not in routing_table:
            continue  # No mapping for this topic, skip it

        ch_id, api_key, field_name = routing_table[topic]
        timestamp = event["timestamp"]  # a ISO8601 string, e.g., "2026-01-26T13:00:00Z"

        # Initialize channel structure if not exists
        if ch_id not in nested_dict:
            nested_dict[ch_id] = {
                "write_api_key": api_key,
                "timestamps": {} 
            }

        # Initialize the timestamp dict if it doesn't exist for this channel
        if timestamp not in nested_dict[ch_id]["timestamps"]:
            nested_dict[ch_id]["timestamps"][timestamp] = {"_room_id": None}

        # Save room_id once per timestamp bucket if the topic follows airguard/<room_id>/...
        room_id = _extract_room_id_from_topic(topic)
        if room_id and nested_dict[ch_id]["timestamps"][timestamp]["_room_id"] is None:
            nested_dict[ch_id]["timestamps"][timestamp]["_room_id"] = room_id
        
        # Merge the fields and value into the specific timestamp dict
        nested_dict[ch_id]['timestamps'][timestamp][field_name] = event["value"]
    
    # Transform the nested dict to match ThingSpeak's expected format
    for ch_id, data in nested_dict.items():
        updates_list = []

        # Iterate through merged timestamp to create the "updates" list
        # ts is the 'timestamp'(iso8601 str), 
        # fields_dict is the dict of fieldN: value pairs for that timestamp 
        # 'fieldN' is determined by the routing table, 'value' is from the event
        for ts, fields_dict in  data["timestamps"].items():
            # Create a single_update dict containing the timestamp
            room_id = fields_dict.pop("_room_id", None)
            single_update = {"created_at": ts}
            if room_id:
                single_update["field1"] = room_id

            # Merge the fieldN: value pairs into the single_update dict
            single_update.update(fields_dict)
            updates_list.append(single_update)
        
        # Final payload for this channel
        payloads_by_channel[ch_id] = {
            "write_api_key": data["write_api_key"],
            "updates": updates_list
        }
            
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