import inspect
from collections.abc import Awaitable, Callable
from typing import Any, cast

from .event import PublishableEvent

type Listener[EventT: PublishableEvent] = Callable[[EventT], Awaitable[None]]

_listeners: dict[str, list[Listener[Any]]] = {}


def listener[EventT: PublishableEvent](
    event: type[EventT],
) -> Callable[[Listener[EventT]], Listener[EventT]]:
    """
    Registers an async function to be called when the event is dispatched.

    Raises:
        TypeError: if the function is not a coroutine function (`async def`)
    """

    def wrapper(func: Listener[EventT]) -> Listener[EventT]:
        # a sync function would be called without being awaited, so its work would silently never happen
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"Listener {func!r} must be an async function")

        listeners = _listeners.setdefault(event.name(), [])
        if func not in listeners:
            listeners.append(cast(Listener[Any], func))
        return func

    return wrapper


def listened_event_names() -> list[str]:
    """Returns the names of the events that have listeners registered in this process."""
    return [name for name, listeners in _listeners.items() if listeners]
