"""
Conflict Resolver.
Supported strategies:
  - prefer_higher_priority  (lower priority number wins)
  - prefer_lower_energy     (prefer fan/window over AC)
  - prefer_comfort          (prefer AC over window)
"""
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Energy cost rank: lower = cheaper
_ENERGY_RANK = {"window": 0, "fan": 1, "ac": 2}


def _energy_rank(device_id: str) -> int:
    dl = device_id.lower()
    for k, v in _ENERGY_RANK.items():
        if k in dl:
            return v
    return 99


def resolve(candidates: List[dict], conflict_rules: List[dict]) -> Tuple[List[dict], List[dict]]:
    """
    Returns (final_actions, filtered_out).
    filtered_out contains actions that were rejected with their reason.
    """
    # Build set of devices already committed (device → winning candidate)
    committed: Dict[str, dict] = {}
    filtered: List[dict] = []

    for rule in conflict_rules:
        rule_type = rule.get("rule", "")
        strategy = rule.get("strategy", "prefer_higher_priority")
        conflict_devices = set(rule.get("devices", []))

        if rule_type != "mutually_exclusive" or not conflict_devices:
            continue

        # Collect all candidates for devices in this conflict group
        in_conflict = [c for c in candidates if c["device"] in conflict_devices]
        if len(in_conflict) <= 1:
            continue

        # Select winner by strategy
        if strategy == "prefer_higher_priority":
            winner = min(in_conflict, key=lambda x: x["priority"])
        elif strategy == "prefer_lower_energy":
            winner = min(in_conflict, key=lambda x: _energy_rank(x["device"]))
        elif strategy == "prefer_comfort":
            winner = max(in_conflict, key=lambda x: _energy_rank(x["device"]))
        else:
            winner = in_conflict[0]

        for c in in_conflict:
            if c["device"] != winner["device"]:
                filtered.append({**c, "filter_reason": f"conflict_with_{winner['device']}"})

    # Build final list: exclude filtered devices
    filtered_devices = {f["device"] for f in filtered}
    final = [c for c in candidates if c["device"] not in filtered_devices]

    return final, filtered
