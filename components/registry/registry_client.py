import httpx
import logging
import os
import socket
import os

logger = logging.getLogger(__name__)

# Base URL for the Catalog Service.
CATALOG_BASE_URL = os.getenv("CATALOG_BASE_URL", "http://catalog_service:8001")

def get_local_ip():
    """Retrieve the container's routable IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

class CatalogRegistry:
    def __init__(self):
        self.service_id = "thingspeak-adaptor"
        self.port = 8000
        self.ip = os.getenv("SERVICE_IP", get_local_ip())
        
    async def register(self):
        """Send POST request to Catalog Service."""
        url = f"{CATALOG_BASE_URL}/services/register"

        # Payload matches teammate's scheduler logic exactly
        payload = {
            "service_id": self.service_id,
            "service_name": "ThingSpeak_Adaptor",
            "endpoint": self.service_url,
            "health_endpoint": "/health",
            "type": "adaptor"
        }

        async with httpx.AsyncClient() as client:
            for attempt in range(1, 6):
                try:
                    response = await client.post(url, json=payload, timeout=5.0)
                    if response.status_code in (200, 201):
                        logger.info("Registered to Catalog Service.")
                        return
                    logger.error(f"Catalog registration failed: {response.text}")
                except Exception as e:
                    logger.warning("Catalog registration attempt %s/5 failed: %s", attempt, e)
                if attempt < 5:
                    await asyncio.sleep(2)
            logger.error("Catalog registration failed after 5 attempts.")

    async def deregister(self):
        """Send DELETE request to Catalog Service."""
        url = f"{CATALOG_BASE_URL}/services/{self.service_id}"

        async with httpx.AsyncClient() as client:
            try:
                await client.delete(url, timeout=3.0)
                logger.info("Deregistered from Catalog Service.")
            except Exception as e:
                logger.error(f"Network error during deregistration: {e}")