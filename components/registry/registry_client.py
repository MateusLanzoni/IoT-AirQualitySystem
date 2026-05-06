import httpx
import logging
import socket

logger = logging.getLogger(__name__)

# Base URL for the Catalog Service. Use Docker compose service name 'catalog_service'
CATALOG_BASE_URL = "http://catalog_service:8001"

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
        self.ip = get_local_ip()
        
    async def register(self):
        """Send POST request to Catalog Service."""
        url = f"{CATALOG_BASE_URL}/services/register"
        
        # Payload matches teammate's scheduler logic exactly
        payload = {
            "service_id": self.service_id,
            "endpoint": f"http://{self.ip}:{self.port}",
            "health_endpoint": "/health"
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=5.0)
                if response.status_code in (200, 201):
                    logger.info("Registered to Catalog Service.")
                else:
                    logger.error(f"Catalog registration failed: {response.text}")
            except Exception as e:
                logger.error(f"Network error during registration: {e}")

    async def deregister(self):
        """Send DELETE request to Catalog Service."""
        url = f"{CATALOG_BASE_URL}/services/{self.service_id}"
        
        async with httpx.AsyncClient() as client:
            try:
                await client.delete(url, timeout=3.0)
                logger.info("Deregistered from Catalog Service.")
            except Exception as e:
                logger.error(f"Network error during deregistration: {e}")