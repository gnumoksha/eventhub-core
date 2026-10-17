from collections.abc import Callable
from typing import Any, cast

from .event import PublishableEvent

_listeners: dict[str, list[Callable[[Any], None]]] = {}


def listener[EventT: PublishableEvent](
    event: type[EventT],
) -> Callable[[Callable[[EventT], None]], Callable[[EventT], None]]:
    def wrapper(func: Callable[[EventT], None]) -> Callable[[EventT], None]:
        listeners = _listeners.setdefault(event.name(), [])
        if func not in listeners:
            listeners.append(cast(Callable[[Any], None], func))
        return func

    return wrapper
