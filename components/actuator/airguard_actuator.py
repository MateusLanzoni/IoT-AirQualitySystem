from components.actuator import ActuatorEntity, ActuatorEntityDescription
from components.drivers.hardware import ActuatorDriver
import logging

from core.event_bus import EventBus
from components.mqtt.const import EVENT_STATE_CHANGED, EVENT_COMMAND_RECEIVED

_LOGGER = logging.getLogger(__name__)

class AirguardActuator(ActuatorEntity):
    def __init__(self, description: ActuatorEntityDescription, driver: ActuatorDriver, bus: EventBus) -> None:
        super().__init__(description)  # Static metadata is handled by the base class constructor
        self._driver = driver
        self.bus = bus
        self._attr_is_on = False

        self.bus.async_listen(EVENT_COMMAND_RECEIVED, self._on_command_received)

    async def _on_command_received(self, event):
        """Handle incoming ALL commands on the event bus."""
        # Check device_id
        if event.data.get("device_id") != self.entity_description.key:
            return
        action = event.data.get("action")
        if action == "turn_on":
            await self.async_turn_on()
        elif action == "turn_off":
            await self.async_turn_off()

    def _fire_state_changed(self):
        """internal method, fire state change event to bus after state is updated."""
        changed_data = {
            "device_id": self.entity_description.key,
            "value": "ON" if self._attr_is_on else "OFF"
        }
        self.bus.async_fire(EVENT_STATE_CHANGED, changed_data)

    async def async_turn_on(self) -> None:
        self._driver.set_state(True)  # Send the command to the simulator via the driver
        self._attr_is_on = True       # Update the internal state to reflect the new status
        _LOGGER.info(f"{self.name} turned ON")

        self._fire_state_changed()

    async def async_turn_off(self) -> None:
        self._driver.set_state(False) # Send the command to the simulator via the driver
        self._attr_is_on = False      # Update the internal state to reflect the new status
        _LOGGER.info(f"{self.name} turned OFF")

        self._fire_state_changed()

    async def async_update(self) -> None:
        old_state = self._attr_is_on
        self._attr_is_on = self._driver.get_state()  # Fetch the current state from the simulator
        

        if old_state != self._attr_is_on:
            self._fire_state_changed()  # Fire event if state has changed

        _LOGGER.info(f"{self.name} updated: {'ON' if self._attr_is_on else 'OFF'}")
    
