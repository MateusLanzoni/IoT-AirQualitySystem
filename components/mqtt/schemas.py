"""

"""

from enum import Enum
from typing import Union, Dict, Any, Optional
from pydantic import BaseModel, Field

class ActionEnum(str, Enum):
    """
    Allowed actions from incoming commands.
    """
    # Lowercase format (internal)
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    SET_VALUE = "set_value"
    # Uppercase format (external compatibility)
    TURN_ON_UPPER = "TURN_ON"
    TURN_OFF_UPPER = "TURN_OFF"

class TelemetryMessage(BaseModel):
    """
    Schema for outgoing sensor data.
    """
    device_id: str = Field(...,description="Unique identifier for the device")
    value: Union[float, int, str] = Field(..., description="The sensor reading or statevalue")
    timestamp: int = Field(..., description="Unix timestamp of the reading")

class CommandMessage(BaseModel):
    """
    Schema for incoming commands from the Decision Service.
    """
    device_id: str = Field(..., description="Target device identifier")
    action: ActionEnum = Field(..., description="The action to perform")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Optional parameters for the action, e.g., temperature for set_value")