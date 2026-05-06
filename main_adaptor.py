import asyncio
import yaml
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

# Import API router
from components.adaptor.api import router

# Import background tasks and registry client
from components.adaptor.ingress_client import start_ingress
from components.adaptor.egress_to_tspeak import start_egress
from components.registry.registry_client import CatalogRegistry


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

# Initialize service registry client
registry = CatalogRegistry()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the lifecycle of the Adaptor application."""
    config = load_config()
    
    # 1. Startup: Launch background asynchronous tasks
    ingress_task = asyncio.create_task(
        start_ingress(broker_host="mosquitto", port=1883, topics=["sensor/#", "actuator/#"])
    )
    egress_task = asyncio.create_task(start_egress(config))
    
    # 2. Startup: Register service to Catalog
    await registry.register()
    
    # Yield control to FastAPI to handle incoming HTTP requests
    yield 
    
    # 3. Shutdown: Deregister service gracefully
    await registry.deregister()
    
    # 4. Shutdown: Cancel background tasks
    ingress_task.cancel()
    egress_task.cancel()
    
    # Wait for tasks to clean up and exit
    try:
        await asyncio.gather(ingress_task, egress_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

# Initialize FastAPI app with lifespan management
app = FastAPI(lifespan=lifespan)

# Mount the Northbound API router
app.include_router(router)

if __name__ == "__main__":
    # Start the ASGI server
    uvicorn.run("main_adaptor:app", host="0.0.0.0", port=8000)