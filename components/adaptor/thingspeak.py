import httpx
import logging
from typing import Optional
from .base import BaseTimeSeriesStorage

logger = logging.getLogger(__name__)

class ThingSpeakProvider(BaseTimeSeriesStorage):
    def __init__(self, config: dict):
        self.channels = config.get("channels", [])

    def _select_channel_for_room(self, roomid: str) -> Optional[dict]:
        room_token = f"/{roomid}/"

        for ch in self.channels:
            fields = ch.get("fields", {})
            has_read_key = bool(ch.get("read_api_key"))
            if not has_read_key:
                continue

            for topic in fields.values():
                if isinstance(topic, str) and room_token in topic:
                    return ch

        # Fallback: first readable channel
        for ch in self.channels:
            if ch.get("read_api_key"):
                return ch
        return None

    async def get_history(self, roomid: str, starttime: str, endtime: str):
        selected_channel = self._select_channel_for_room(roomid)
        if not selected_channel:
            return {"error": f"No readable channel found for room '{roomid}'."}

        channel_id = str(selected_channel.get("channel_id"))
        read_api_key = selected_channel.get("read_api_key")

        # feed
        url = f"https://api.thingspeak.com/channels/{channel_id}/feeds.json"

        params = {
            "api_key": read_api_key,
            "start": starttime,
            "end": endtime
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url, params=params)
                # log the raw response for debugging
                logger.debug(f"ThingSpeak API response: {response.status_code}")

                if response.status_code != 200:
                    # Log the error response for debugging
                    logger.error(f"ThingSpeak API error: {response.status_code} - {response.text}")
                    return {"error": f"ThingSpeak API error: {response.status_code} - {response.text}"}

                raw_data = response.json()
                clean_data = []

                for item in raw_data.get("feeds", []):
                    record = {"created_at": item.get("created_at")}

                    # Keep ThingSpeak field payload shape, e.g. field1, field2, ...
                    for key, value in item.items():
                        if key.startswith("field") and value is not None:
                            record[key] = value
                    clean_data.append(record)

                    logger.debug("Processed record and added to feed")
                return clean_data

            except httpx.RequestError as e:
                return {"error": f"HTTP request failed: {str(e)}"}

