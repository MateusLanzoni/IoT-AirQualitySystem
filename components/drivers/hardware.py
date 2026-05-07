"""
This module contains the hardware drivers for the simulated sensors and actuators.
"""

import random
import math
import time
import logging
from collections import deque

from components.mqtt.const import EVENT_STATE_CHANGED

_LOGGER = logging.getLogger(__name__)

class SensorDriver:
    def __init__(self, sensor_key: str, sensor_config: dict, bus=None) -> None:
        """
        Initialize sensor driver with config-based parameters.
        
        Args:
            sensor_key: sensor identifier (e.g., "temp_01")
            sensor_config: dict with base_val, noise, and effect parameters
            bus: EventBus to listen to actuator state changes (optional)
        """
        self.sensor_key = sensor_key
        self.base_val = sensor_config.get("base_val", 20.0)
        self.noise = sensor_config.get("noise", 1.0)
        self.bus = bus

        # Smoothing constraints: each update changes at most 0.5% by default.
        self.max_step_ratio = sensor_config.get("max_step_ratio", 0.005)
        self.min_step_abs = sensor_config.get("min_step_abs", 0.0)

        # Daily physical trend: one full sine cycle in 24 hours.
        self.trend_period_sec = sensor_config.get("trend_period_sec", 86400.0)
        self.trend_amplitude = sensor_config.get(
            "trend_amplitude",
            max(abs(self.base_val) * 0.08, 0.5)
        )

        # Low-pass filter to soften short-term jitter before step limiting.
        self.trend_smoothing_window = max(1, int(sensor_config.get("trend_smoothing_window", 5)))
        self.target_history = deque(maxlen=self.trend_smoothing_window)
        
        # Actuator effects (will be updated by bus listener)
        self.ac_on = False
        self.fan_on = False
        self.window_on = False
        
        # Effect parameters from config
        self.ac_effect = sensor_config.get("ac_effect", 0.0)        # °C per second
        self.ac_min = sensor_config.get("ac_min", float('-inf'))
        self.fan_effect = sensor_config.get("fan_effect", 0.0)      # % per second
        self.fan_min = sensor_config.get("fan_min", float('-inf'))
        self.window_effect = sensor_config.get("window_effect", 0.0) # ppm/µg per second
        self.window_min = sensor_config.get("window_min", float('-inf'))
        
        # Maintain current value (accumulates changes)
        self.current_value = self.base_val
        self.dynamic_offset = 0.0
        self.last_output = self.base_val
        self.last_update_time = time.time()
        
        # Subscribe to bus if provided
        if self.bus:
            self.bus.async_listen(EVENT_STATE_CHANGED, self._on_state_changed)
    
    async def _on_state_changed(self, event):
        """Listen for actuator state changes from the event bus."""
        data = event.data
        device_id = data.get("device_id", "")
        state = data.get("value")
        
        # Map device state to actuator flags
        if "ac" in device_id.lower():
            self.ac_on = bool(state)
        elif "fan" in device_id.lower():
            self.fan_on = bool(state)
        elif "window" in device_id.lower():
            self.window_on = bool(state)
    
    async def read_data(self) -> float:
        """Generate sensor reading with actuator effects and natural variation."""
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time

        if dt <= 0:
            dt = 1.0
        
        # Base variation: 24-hour sine trend to mimic realistic daily changes.
        trend = self.trend_amplitude * math.sin((2.0 * math.pi * current_time) / self.trend_period_sec)
        
        # Actuator effects are accumulated into a dynamic offset.
        actuator_delta = 0.0
        min_value = float('-inf')
        
        if self.ac_on:
            actuator_delta += self.ac_effect * dt
            min_value = max(min_value, self.ac_min)
        if self.fan_on:
            actuator_delta += self.fan_effect * dt
            min_value = max(min_value, self.fan_min)
        if self.window_on:
            actuator_delta += self.window_effect * dt
            min_value = max(min_value, self.window_min)

        self.dynamic_offset += actuator_delta

        # Target value follows daily trend + actuator dynamic effect.
        target_value = self.base_val + trend + self.dynamic_offset

        # Clamp target to configured minima when related actuators are active.
        if min_value != float('-inf'):
            target_value = max(target_value, min_value)

        # Smooth the target with a short moving average.
        self.target_history.append(target_value)
        smoothed_target = sum(self.target_history) / len(self.target_history)

        # Apply max 0.5% step smoothing from current value towards smoothed target value.
        max_step = max(abs(self.current_value) * self.max_step_ratio, self.min_step_abs)
        desired_delta = smoothed_target - self.current_value
        bounded_delta = max(-max_step, min(max_step, desired_delta))
        self.current_value += bounded_delta
        
        # Add bounded noise so jitter cannot break the 1% per-update cap.
        max_noise = max_step * 0.3
        noise = random.gauss(0.0, self.noise)
        noise = max(-max_noise, min(max_noise, noise))
        final_value = self.current_value + noise

        # Final safety clamp: ensure output changes at most 0.5% per update.
        output_step_cap = max(abs(self.last_output) * self.max_step_ratio, self.min_step_abs)
        output_delta = final_value - self.last_output
        bounded_output_delta = max(-output_step_cap, min(output_step_cap, output_delta))
        final_value = self.last_output + bounded_output_delta
        self.last_output = final_value
        
        return round(final_value, 2)
    
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

