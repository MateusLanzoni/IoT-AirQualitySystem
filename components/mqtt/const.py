"""
Topic example:
airguard/room1/telemetry/sensor/sensor_001/
{"temperature": 25.5, "humidity": 60, "battery": 98, "timestamp": 1712580000}
"""

# Base namespace for the edge device
TOPIC_PREFIX = "airguard/room1"

# Topic templates for routing
# Usage format: airguard/room1/telemetry/<device_type>/<device_id>
TOPIC_TELEMETRY = f"{TOPIC_PREFIX}/telemetry/{{device_type}}/{{device_id}}"

# Publish state feedback (e.g., actuator confirmation)
# Usage format: airguard/room1/state/<device_type>/<device_id>
TOPIC_STATE = f"{TOPIC_PREFIX}/state/{{device_type}}/{{device_id}}"

# Subscribe to incoming commands from Decision Service
# usage format: airguard/room1/command/<device_type>/<device_id>
TOPIC_COMMAND = f"{TOPIC_PREFIX}/command/{{device_type}}/{{device_id}}"

# Json keys
PAYLOAD_KEY_DEVICE_ID = "device_id"
PAYLOAD_KEY_VALUE = "value"
PAYLOAD_KEY_TIMESTAMP = "timestamp"
PAYLOAD_KEY_ACTION = "action"
PAYLOAD_KEY_PARAMS = "params"

# Internal Event Bus types
EVENT_STATE_CHANGED = "state_changed"        # Used for Telemetry 
EVENT_COMMAND_RECEIVED = "command_received"  # Used for Actuation
EVENT_AVAILABILITY_CHANGED = "availability"  # Used for LWT/Online 