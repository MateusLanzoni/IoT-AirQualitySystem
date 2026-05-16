import httpx
import logging
from typing import List, Dict, Any, Union
from .base import BaseTimeSeriesStorage

logger = logging.getLogger(__name__)

class ThingSpeakProvider(BaseTimeSeriesStorage):
    def __init__(self, config: dict):
        # Read channel id and API key
        self.channel_id = None
        self.read_api_key = None
    
        for ch in config.get("channels", []):
            if ch.get("read_api_key"):
                self.channel_id = str(ch.get("channel_id"))
                self.read_api_key = ch.get("read_api_key")
                break

    async def get_history(self, roomid: str, starttime: str, endtime: str):
        if not self.channel_id:
            return {"error": "No valid channel."}
        
        # feed
        url = f"https://api.thingspeak.com/channels/{self.channel_id}/feeds.json"

        params = {
            "api_key": self.read_api_key,
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
                    # Field1 is roomid, we filter by it
                    if item.get("field1") == roomid:
                        record = {"created_at": item.get("created_at")}

                        # Dynamically add all fieldN values
                        for key, value in item.items():
                            if key.startswith("field") and value is not None:
                                record[key] = value
                        clean_data.append(record)

                        # Log each record for debugging
                        logger.debug(f"Processed record and added to feed")
                return clean_data
            
            except httpx.RequestError as e:
                return {"error": f"HTTP request failed: {str(e)}"}
            
            