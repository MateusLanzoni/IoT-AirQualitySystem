"""
This module contains the hardware drivers for the simulated sensors and actuators.
"""

import random
import math
import time
import logging

_LOGGER = logging.getLogger(__name__)

class SensorDriver:
    def __init__(self, base_val: float, noise: float) -> None:
        self.base_val = base_val
        self.noise = noise
    
    async def read_data(self) -> float:
        trend = 5.0 * math.sin(time.time() / 3600.0)
        noise = random.gauss(0.0, self.noise)
        return round(self.base_val + trend + noise, 2)
    
class ActuatorDriver:
    def __init__(self, initial_state: bool = False) -> None:
        self._is_on = initial_state
    
    # Pass the desired state to the simulator, which will update the internal state accordingly
    def set_state(self, state: bool) -> None:
        self._is_on = state
        state_str = "ON" if state else "OFF"
        _LOGGER.info(f"Actuator state set to: {state_str}")
    
    # Get the current state from the simulator, which reflects the last command sent via set_state
    def get_state(self) -> bool:
        return self._is_on

