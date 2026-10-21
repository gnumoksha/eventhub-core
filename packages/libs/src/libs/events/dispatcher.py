from abc import ABC, abstractmethod
from typing import override

from .event import PublishableEvent
from .listener import _listeners
from .logger import logger


class EventDispatchError(Exception):
    """Raised when an event could not be published."""


class Dispatcher(ABC):
    @abstractmethod
    async def dispatch(self, event: PublishableEvent) -> None:
        """
        Raises:
            EventDispatchError:
        """
        pass


class LocalDispatcher(Dispatcher):
    """Calls the listeners registered in this process, one after the other."""

    @override
    async def dispatch(self, event: PublishableEvent) -> None:
        if event.name() not in _listeners:
            logger.warning(
                "No listeners registered for event: %s. If it came from a RabbitMQ queue, the queue probably has "
                "an obsolete binding for it (e.g. its listener was removed); remove the binding manually.",
                event.name(),
            )
            return

        # sequentially, so a failure stops the next listeners and the whole event is retried (listeners are idempotent)
        for func in _listeners[event.name()]:
            await func(event)


class RecordingDispatcher(Dispatcher):
    def __init__(self) -> None:
        self.dispatched: list[PublishableEvent] = []

    @override
    async def dispatch(self, event: PublishableEvent) -> None:
        self.dispatched.append(event)
