from abc import ABC, abstractmethod
from typing import override

from .event import PublishableEvent
from .listener import _listeners
from .logger import logger


class EventDispatchError(Exception):
    """Raised when an event could not be published."""


class Dispatcher(ABC):
    @abstractmethod
    def dispatch(self, event: PublishableEvent) -> None:
        """
        Raises:
            EventDispatchError:
        """
        pass


class SyncDispatcher(Dispatcher):
    @override
    def dispatch(self, event: PublishableEvent) -> None:
        if event.name() not in _listeners:
            logger.warning("No listeners registered for event: %s", event.name())
            return

        for func in _listeners[event.name()]:
            func(event)
