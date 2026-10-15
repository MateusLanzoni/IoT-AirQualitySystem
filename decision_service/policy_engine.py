"""
Policy Engine: evaluates room policies against current sensor metrics.
Returns a list of candidate actions sorted by priority (ascending = higher priority first).
"""
import logging
import operator as op
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_OPS = {
    ">": op.gt,
    "<": op.lt,
    ">=": op.ge,
    "<=": op.le,
    "==": op.eq,
}


def _eval_condition(metric_val: float, operator: str, threshold: float) -> bool:
    fn = _OPS.get(operator)
    if fn is None:
        logger.warning(f"Unknown operator: {operator}")
        return False
    return fn(metric_val, threshold)


def evaluate(metrics: Dict[str, float], policies: List[dict], predictions: Optional[dict] = None) -> List[dict]:
    """
    Evaluate each policy against current metrics (and optionally predictions).
    Returns candidate actions: [{"device": str, "state": str, "priority": int, "reason": str}]
    """
    candidates = []

    for policy in policies:
        metric_name = policy.get("metric", "")
        operator = policy.get("operator", ">")
        threshold = policy.get("value", 0)
        target_device = policy.get("target_device", "")
        target_state = policy.get("target_state", "ON")
        priority = policy.get("priority", 99)

        metric_val = metrics.get(metric_name)
        logger.debug("polucy, metric_val: %s", metric_val)
        if metric_val is None:
            # Try from predictions
            if predictions and metric_name in predictions:
                metric_val = predictions[metric_name].get("value")
        if metric_val is None:
            continue

        if _eval_condition(metric_val, operator, threshold):
            candidates.append({
                "device": target_device,
                "state": target_state,
                "priority": priority,
                "reason": f"{metric_name}_{operator}_{threshold}",
            })
            logger.debug(f"Policy triggered: {metric_name}={metric_val} {operator} {threshold} → {target_device}={target_state}")

    # Sort by priority ascending (lower number = higher priority)
    candidates.sort(key=lambda x: x["priority"])
    return candidates
