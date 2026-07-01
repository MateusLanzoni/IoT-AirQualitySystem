"""
In-memory state buffer for ThingSpeak Adaptor Component.
Queue-based in-memory buffer.
Stores raw (topic, value, timestamp) events safely.
"""
import time
from collections import deque
from typing import Any, Dict, List

class EventQueueBuffer:
    def __init__(self) -> None:
        # A single, flat queue for all incoming raw events
        self._queue: deque = deque()

    def push_event(self, topic: str, payload: Any) -> None:
        """
        Appends a raw MQTT event. 
        Ingress stays blind: no channel or field logic here.
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._queue.append({
            "topic": topic,
            "value": payload,
            "timestamp": timestamp
        })

    def drain_all(self) -> List[Dict[str, Any]]:
        """
        Safely extracts all events by replacing the queue instance.
        Prevents data loss during async context switches.
        """
        if not self._queue:
            return []
            
        # Atomic pointer swap: Take the full queue, leave a fresh empty one
        current_queue = self._queue
        self._queue = deque()
        
        return list(current_queue)

buffer_instance = EventQueueBuffer()