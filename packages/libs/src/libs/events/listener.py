from collections.abc import Callable
from typing import ParamSpec, TypeVar

from .event import PublishableEvent

P = ParamSpec("P")
R = TypeVar("R")

_listeners: dict[str, list[Callable[[PublishableEvent], None]]] = {}


def listener(event: type[PublishableEvent]):
    def wrapper(func: Callable[P, R]) -> Callable[P, R]:
        _listeners.setdefault(event.name(), []).append(func)  # ty:ignore[invalid-argument-type]
        return func

    return wrapper
