"""
Energy Mode adjustments.
NORMAL       : no change
ENERGY_SAVING: increase effective priority of high-power devices (AC)
               unless critical thresholds are exceeded.
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

HIGH_POWER_TYPES = {"AC"}


def is_critical(metrics: Dict[str, float], cfg: dict) -> bool:
    co2_limit = cfg.get("critical_co2", 2000)
    temp_limit = cfg.get("critical_temperature", 35)
    return (
        metrics.get("co2", 0) > co2_limit
        or metrics.get("temperature", 0) > temp_limit
    )


def apply(candidates: List[dict], energy_mode: str, metrics: Dict[str, float], cfg: dict) -> List[dict]:
    """
    Adjust candidate priorities according to energy mode.
    Returns a new list with updated priorities.
    """
    if energy_mode != "ENERGY_SAVING":
        return candidates

    if is_critical(metrics, cfg):
        logger.info("Critical thresholds exceeded — energy saving suppressed")
        return candidates

    penalty = cfg.get("ac_energy_penalty", 2)
    adjusted = []
    for c in candidates:
        device_id = c["device"].lower()
        # Apply penalty to AC devices (check device id contains 'ac')
        if "ac" in device_id:
            c = dict(c)
            c["priority"] = c["priority"] + penalty
            logger.debug(f"Energy penalty applied to {c['device']}: priority → {c['priority']}")
        adjusted.append(c)

    # Re-sort after adjustment
    adjusted.sort(key=lambda x: x["priority"])
    return adjusted
