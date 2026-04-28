from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .schemas import HistoryPoint, HistoryResponse, IndoorSnapshot, OutdoorSnapshot, ServiceRegistrationPayload


@dataclass
class ClientBundle:
    room_catalog: "RoomCatalogClient"
    thingspeak: "ThingSpeakAdapterClient"
    outdoor_aqi: "OutdoorAqiClient"


class RoomCatalogClient:
    def __init__(self, base_url: str, register_path: str, heartbeat_path: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.register_path = register_path
        self.heartbeat_path = heartbeat_path
        self.timeout = timeout

    async def register_service(self, payload: ServiceRegistrationPayload) -> dict[str, Any]:
        url = f"{self.base_url}{self.register_path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload.model_dump())
            response.raise_for_status()
            return response.json() if response.content else {"status": "ok"}

    async def heartbeat(self, service_id: str, status: str = "online") -> dict[str, Any]:
        path = self.heartbeat_path.format(service_id=service_id)
        url = f"{self.base_url}{path}"
        payload = {"service_id": service_id, "status": status}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.put(url, json=payload)
            response.raise_for_status()
            return response.json() if response.content else {"status": "ok"}


class ThingSpeakAdapterClient:
    def __init__(self, base_url: str, history_path: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.history_path = history_path
        self.timeout = timeout

    async def fetch_history(self, room_id: str, lookback_points: int) -> HistoryResponse:
        url = f"{self.base_url}{self.history_path}"
        params = {"room_id": room_id, "limit": lookback_points}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        return normalize_history_response(room_id, data)


class OutdoorAqiClient:
    def __init__(self, base_url: str, path: str, token: str | None, city: str, source_name: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.path = path.strip("/")
        self.token = token
        self.city = city
        self.source_name = source_name
        self.timeout = timeout

    async def fetch_current(self, override_aqi: float | None = None) -> OutdoorSnapshot:
        if override_aqi is not None:
            return OutdoorSnapshot(
                aqi=override_aqi,
                source="override",
                fetched_at=datetime.now(timezone.utc),
            )

        if not self.token:
            return OutdoorSnapshot(
                aqi=None,
                source="unconfigured",
                fetched_at=datetime.now(timezone.utc),
            )

        url = f"{self.base_url}/{self.path}/{self.city}/"
        params = {"token": self.token}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        aqi = None
        if isinstance(data, dict):
            aqi = data.get("data", {}).get("aqi")

        return OutdoorSnapshot(
            aqi=float(aqi) if aqi is not None else None,
            source=self.source_name,
            fetched_at=datetime.now(timezone.utc),
        )


def normalize_history_response(room_id: str, payload: Any) -> HistoryResponse:
    if isinstance(payload, dict) and "points" in payload:
        points = [HistoryPoint.model_validate(normalize_point(item, room_id)) for item in payload.get("points", [])]
        latest = payload.get("latest")
        return HistoryResponse(
            room_id=payload.get("room_id", room_id),
            points=points,
            latest=IndoorSnapshot.model_validate(latest) if latest else derive_latest(points),
            raw=payload,
        )

    if isinstance(payload, list):
        points = [HistoryPoint.model_validate(normalize_point(item, room_id)) for item in payload]
        return HistoryResponse(room_id=room_id, points=points, latest=derive_latest(points), raw={"items": payload})

    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("data") or payload.get("history") or []
        points = [HistoryPoint.model_validate(normalize_point(item, room_id)) for item in items]
        return HistoryResponse(room_id=room_id, points=points, latest=derive_latest(points), raw=payload)

    raise ValueError("Unsupported ThingSpeak Adapter response shape")


def normalize_point(item: dict[str, Any], room_id: str) -> dict[str, Any]:
    def pick(*values):
        for value in values:
            if value is not None:
                return value
        return None

    return {
        "timestamp": pick(item.get("timestamp"), item.get("created_at")),
        "room_id": pick(item.get("room_id"), room_id),
        "device_id": item.get("device_id"),
        "temperature": pick(item.get("temperature"), item.get("field2")),
        "humidity": pick(item.get("humidity"), item.get("field3")),
        "pm25": pick(item.get("pm25"), item.get("field4"), item.get("pm2_5")),
        "co2": pick(item.get("co2"), item.get("field5")),
        "source": pick(item.get("source"), "thingspeak-adapter"),
    }


def derive_latest(points: list[HistoryPoint]) -> IndoorSnapshot | None:
    if not points:
        return None
    latest = sorted(points, key=lambda point: point.timestamp)[-1]
    return IndoorSnapshot(
        temperature=latest.temperature,
        humidity=latest.humidity,
        co2=latest.co2,
        pm25=latest.pm25,
    )
