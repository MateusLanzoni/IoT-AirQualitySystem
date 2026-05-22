"""
REST API Interface for monitoring the Adaptor .
"""
import yaml
from datetime import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
import logging

from components.adaptor.base import BaseTimeSeriesStorage
from components.adaptor.thingspeak import ThingSpeakProvider

router = APIRouter()
logger = logging.getLogger(__name__)

def load_config() -> Dict[str, Any]:
    with open("components/adaptor/config.yaml", "r") as f:
        return yaml.safe_load(f)

# Global singleton initialization
_config = load_config()
_storage_provider = ThingSpeakProvider(_config)

def get_storage() -> BaseTimeSeriesStorage:
    """Dependency injection for storage provider. Currently hardcoded to ThingSpeakProvider.
    """
    return _storage_provider

@router.get("/health")
async def health_check():
    """Liveness probe endpoint"""
    return {"status": "ok", "service": "thingspeak_adaptor_api"}

@router.get("/api/v1/history", response_model=List[Dict[str, Any]])
async def get_history(
    roomid: str = Query(...,description="Target room"),
    starttime: datetime = Query(...,description="Start time, e.g., 2026-01-26T13:00:00Z)"),
    endtime: datetime = Query(...,description="End time, e.g., 2026-01-26T14:00:00Z)"),
    db: BaseTimeSeriesStorage = Depends(get_storage)
):
    """
    Retrieves historical data for a given room and time range.
    Rerurns a list of events containing 'created_at' and all dynamic fields. 
    """
    # Format datetime objects to thingspeak's expected string format
    start_str = starttime.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = endtime.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Log the query parameters for debugging
    logger.info(f"Fetching history for room {roomid} from {start_str} to {end_str}")

    # Call the abstracted storage 
    result = await db.get_history(
        roomid = roomid,
        starttime = start_str,
        endtime = end_str
    )

    # Handle provider errors
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result