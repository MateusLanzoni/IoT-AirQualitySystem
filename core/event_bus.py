"""

"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List

_LOGGER = logging.getLogger(__name__)

class Event:
    """
    Standard format for events in the system.
    """
    def __init__(self, event_type: str, data: Dict[str, Any] = None):
        self.event_type = event_type
        self.data = data or {}

class EventBus:
    """
    This is a central system of Edge Gateway;
    A non-blocking, task-spawning architecture"""

    def __init__(self):
        # Mapping event_type -> list of async callback functions
        self._listeners: Dict[str, List[Callable[[Event],Coroutine[Any, Any, None]]]] = {}

    def async_listen(self, event_type: str, listener: Callable[[Event], Coroutine[Any, Any, None]]) -> Callable[[], None]:
        """
        Register an async listener for a specific event type.
        
        returns:
            (unsubscribe) A function that can be called to remove this listener.    
        """

        self._listeners.setdefault(event_type, []).append(listener)

        _LOGGER.debug(f"Added listener for event: {event_type}")

        # A way to unsubscribe (useful for graceful shutdown
        def remove_listener():
            try:
                self._listeners[event_type].remove(listener)
                _LOGGER.debug(f"Removed listener for event: {event_type}")

            except ValueError:
                pass
        
        return remove_listener
    
    def async_fire(self, event_type: str, event_data: Dict[str, Any] = None) -> None:
        """
        Fire an event to a bus.
        """
        listeners = self._listeners.get(event_type, [])
        if not listeners:
            # No one is listening to this event, drop it
            return
        
        event = Event(event_type, event_data)

        for listener in listeners:
            # Instead of waiting for the listener to finish, we wrap it in a background Task 
            # and throw it to the asyncio event loop.
            asyncio.create_task(
                self._async_dispatch_safely(listener, event),
                name = f"EventDispatch-{event_type}"
            )
        
    async def _async_dispatch_safely(self, listener: Callable, event: Event) -> None:
        """
        Wrapper to execute the listener safely.
        Prevents one misbehaving listener from crashing the entire event loop.
        """
        try:
            await listener(event)
        except Exception as err:
            # If a sensor throws an error,log it 
            _LOGGER.error(
                "Error listener '%s' for event '%s': %s",
                listener.__name__,
                event.event_type,
                err
            )


