import yaml
import logging
import asyncio

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

        # Create a dynamic sensor driver instance with parameters from config
        driver = SensorDriver(base_val=item["base_val"], noise=item["noise"])

        # Create the sensor instance with the dynamically created description and driver
        sensors.append(AirguardSensor(description=desc, driver=driver, bus=bus))
    return sensors

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
    # Load configuration from YAML file ,later catalog from outside
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    
    # Initialize the event bus only once 
    bus = EventBus()

    # Boot the MQTT Gateway
    mqtt_gateway = MQTTGateway(bus)
    asyncio.create_task(mqtt_gateway.start())
    
    # test , listen to all state change events and print them out
    bus.async_listen(EVENT_STATE_CHANGED, test_bus_monitor)
    
    # Initialize sensors and actuators, and register them to the bus
    all_sensors = setup_sensors_from_catalog(config.get("sensors", []), bus)
    all_actuators = setup_actuators_from_catalog(config.get("actuators", []), bus)

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
    asyncio.run(main())