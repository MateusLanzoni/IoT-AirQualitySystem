from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Defines standard categories of sensors 
class SensorDeviceClass(StrEnum):
    TEMPERATURE = "temperature"                   # Constant representing a temp sensor
    HUMIDITY = "humidity"
    AQI = "aqi"
    PM25 = "pm25"

# sensor metadata, strictly separating config from operation logic
@dataclass
class SensorEntityDescription:
    key: str                                       # A unique identifier for this specific sensor instance in the system
    device_class: SensorDeviceClass | None = None  # The physical category of the sensor
    native_unit_of_measurement: str | None = None  # The physical unit of the raw data (e.g., '°C')
    name: str | None = None                        # The human-readable name of the sensor for display purposes
    room_id: str | None = None                     # The room where the sensor is located, for contextual grouping

# The core base class for all sensor in the project
class SensorEntity:
    entity_description: SensorEntityDescription    # The static metadata variable
    _attr_native_value: float | None = None        # the private variable to hold the current sensor value from simulator

    def __init__(self, description: SensorEntityDescription) -> None:
        self.entity_description = description
    
    @property
    def name(self) -> str | None:
        return self.entity_description.name
    
    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.entity_description.native_unit_of_measurement
    
    @property
    def device_class(self) -> SensorDeviceClass | None:
        return self.entity_description.device_class
    
    @property
    def native_value(self) -> float | None:
        return self._attr_native_value
    
    @property
    def state(self) -> Any:
        # This method can be overridden by subclasses to provide a more user-friendly state representation
        return self.native_value
    
    async def async_update(self) -> None:
        # This method should be overridden by subclasses to fetch the latest sensor value from the simulator
        pass # Placeholder
