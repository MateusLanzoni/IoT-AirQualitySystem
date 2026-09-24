from components.drivers.hardware import SensorDriver
from components.sensor import SensorEntity, SensorEntityDescription, SensorDeviceClass
import logging
from core.event_bus import EventBus
from components.mqtt.const import EVENT_STATE_CHANGED

_LOGGER = logging.getLogger(__name__)

# 
class AirguardSensor(SensorEntity):
    def __init__(self, description: SensorEntityDescription, driver: SensorDriver, bus: EventBus) -> None:
        super().__init__(description)  # Static metadata is handled by the base class constructor
        self._driver = driver          # Bound logic to fetch data from the simulator via the driver
        self._bus = bus                # Event bus for firing state change events
        self._state = None             # old state

    @property
    def state(self):
        return self._state

    async def async_update(self) -> None:
        # hardware read data,and decide whether to fire event
        new_value = await self._driver.read_data()

        if new_value == self._state:
            return
        
        self._state = new_value

        # Payload format
        event_data = {
            "device_id": self.entity_description.key,
            "value": self._state,
            "unit": self.entity_description.native_unit_of_measurement,
        }

        self._bus.async_fire(EVENT_STATE_CHANGED, event_data)
        _LOGGER.info(f"Sensor {self.name} updated: {event_data}")

        
            