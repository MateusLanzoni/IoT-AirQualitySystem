from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Defines standard categories of actuators
class ActuatorDeviceClass(StrEnum):
    SWITCH = "switch"   # Fans
    CLIMATE = "climate" # AC units

@dataclass
class ActuatorEntityDescription:
    key: str
    name: str
    device_class: ActuatorDeviceClass
    room_id: str | None = None

class ActuatorEntity:
    entity_description: ActuatorEntityDescription
    _attr_is_on: bool | None = None

    def __init__(self, description: ActuatorEntityDescription) -> None:
        self.entity_description = description
    
    @property
    def name(self) -> str:
        return self.entity_description.name
    
    @property
    def is_on(self) -> bool:
        return self._attr_is_on
    
    async def async_turn_on(self) -> None:
        pass

    async def async_turn_off(self) -> None:
        pass

    async def async_update(self) -> None:
        pass
     