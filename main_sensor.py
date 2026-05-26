import logging
import asyncio
import os
import sys
import httpx
import yaml

# Sensor
from components.sensor.airguard_sensor import AirguardSensor
from components.sensor import SensorEntityDescription, SensorDeviceClass
from components.drivers.hardware import SensorDriver

# Actuator
from components.actuator.airguard_actuator import AirguardActuator
from components.actuator import ActuatorEntityDescription, ActuatorDeviceClass
from components.drivers.hardware import ActuatorDriver

# Event bus
from core.event_bus import EventBus
from components.mqtt.client import MQTTGateway
from components.mqtt.const import EVENT_STATE_CHANGED

_LOGGER = logging.getLogger(__name__)

# Setup sensors from catalog
def setup_sensors_from_catalog(config_list: list, bus: EventBus) -> list:
    sensors = []
    for item in config_list:
        # Dynamically create descriptions based on config
        desc = SensorEntityDescription(
            key = item["key"],
            name = item["name"],
            device_class = SensorDeviceClass(item["device_class"]),
            native_unit_of_measurement = item["unit"]
        )

        # Create sensor driver with full config (base_val, noise, effects)
        driver = SensorDriver(
            sensor_key=item["key"],
            sensor_config=item,
            bus=bus
        )

        # Create the sensor instance with the dynamically created description and driver
        sensors.append(AirguardSensor(description=desc, driver=driver, bus=bus))
    return sensors

# Read sensors config from catalog
async def get_devices_from_catalog(url: str):
    """Fetch device configurations from the catalog service."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{url}/devices")
        data = response.json()
        return data.get("data", [])

# Test
async def test_bus_monitor(event):
    print(f"\n [Bus Monitor] Event Fired: {event.event_type} with data: {event.data}\n")


# Setup actuators from catalog
def setup_actuators_from_catalog(config_list: list, bus: EventBus) -> list:
    actuators = []
    for item in config_list:
        desc = ActuatorEntityDescription(

            key = item["key"],
            name=item["name"],
            device_class=ActuatorDeviceClass(item["device_class"])
        )
        driver = ActuatorDriver()
        actuators.append(AirguardActuator(description=desc, driver=driver, bus=bus))
    return actuators


async def main():
    # Load sensor-specific parameters from configuration file
    with open("sensor_value_config.yaml", "r") as f:
        sensor_config_data = yaml.safe_load(f)
    # Create mapping: sensor_key → sensor_config
    sensor_params_map = {s["key"]: s for s in sensor_config_data.get("sensors", [])}

    # Load configuration from YAML file ,later catalog from outside
    catalog_url = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8001")
    all_devices = await get_devices_from_catalog(catalog_url)

    # Separate sensors and actuators based on device_class
    sensors_config = [d for d in all_devices if d["category"] == "sensor"]
    actuators_config = [d for d in all_devices if d["category"] == "actuator"]

    # Merge sensor-specific parameters into sensor config from catalog
    for sensor_cfg in sensors_config:
        sensor_key = sensor_cfg["key"]
        if sensor_key in sensor_params_map:
            sensor_cfg.update(sensor_params_map[sensor_key])

    # Initialize the event bus only once
    bus = EventBus()

    # Boot the MQTT Gateway
    mqtt_gateway = MQTTGateway(bus)
    asyncio.create_task(mqtt_gateway.start())

    # test , listen to all state change events and print them out
    bus.async_listen(EVENT_STATE_CHANGED, test_bus_monitor)

    # Initialize sensors and actuators, and register them to the bus
    all_sensors = setup_sensors_from_catalog(sensors_config, bus)
    all_actuators = setup_actuators_from_catalog(actuators_config, bus)

    _LOGGER.info(f"Initialized {len(all_sensors)} sensors with Event Bus")
    _LOGGER.info(f"Initialized {len(all_actuators)} actuators with Event Bus")
    #print(f"Initialized {len(all_sensors)} sensors from config.")

    while True:
        # Trigger sensors to read hardware
        for sensor in all_sensors:
            await sensor.async_update()   # Update each sensor to fetch the latest value from the simulator
            #print(f"{sensor.name}: {sensor.state} {sensor.native_unit_of_measurement}")

        # Trigger actuators to update
        for actuator in all_actuators:
            await actuator.async_update() # Update each actuator to fetch the latest state from the simulator

        await asyncio.sleep(30)            # Wait for 30 seconds before the next update cycle

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())