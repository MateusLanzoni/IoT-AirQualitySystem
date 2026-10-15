"""
CherryPy REST API Interface for monitoring the Adaptor.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict

import cherrypy
import yaml

from components.adaptor.base import BaseTimeSeriesStorage
from components.adaptor.thingspeak import ThingSpeakProvider

logger = logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    with open("components/adaptor/config.yaml", "r") as f:
        return yaml.safe_load(f)


_config = load_config()
_storage_provider = ThingSpeakProvider(_config)


def get_storage() -> BaseTimeSeriesStorage:
    """Return the configured storage provider."""
    return _storage_provider


def _json_response(payload: Any, status: int = 200) -> str:
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = "application/json"
    return json.dumps(payload, ensure_ascii=False, default=str)


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _run_async(coro):
    return asyncio.run(coro)


class HistoryController:
    def __init__(self, storage: BaseTimeSeriesStorage):
        self._storage = storage

    @cherrypy.expose
    def history(self, roomid=None, starttime=None, endtime=None):
        if not roomid or not starttime or not endtime:
            return _json_response({"error": "roomid, starttime and endtime are required"}, 400)

        try:
            start_dt = _parse_datetime(starttime)
            end_dt = _parse_datetime(endtime)
        except ValueError:
            return _json_response({"error": "Invalid datetime format"}, 400)

        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(f"Fetching history for room {roomid} from {start_str} to {end_str}")

        result = _run_async(self._storage.get_history(roomid=roomid, starttime=start_str, endtime=end_str))
        if isinstance(result, dict) and "error" in result:
            return _json_response({"error": result["error"]}, 400)
        return _json_response(result)


class ApiV1Controller:
    def __init__(self, storage: BaseTimeSeriesStorage):
        self.history = HistoryController(storage)


class ApiController:
    def __init__(self, storage: BaseTimeSeriesStorage):
        self.v1 = ApiV1Controller(storage)


class AdaptorAPI:
    def __init__(self, storage: BaseTimeSeriesStorage | None = None):
        self._storage = storage or get_storage()
        self.api = ApiController(self._storage)

    @cherrypy.expose
    def health(self):
        return _json_response({"status": "ok", "service": "thingspeak_adaptor_api"})