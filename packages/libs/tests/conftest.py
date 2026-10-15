from collections.abc import Iterator
from typing import override

import pytest
from libs.events.event import Config
from libs.events.listener import _listeners


@pytest.fixture(autouse=True)
def clean_listeners() -> Iterator[None]:
    yield
    _listeners.clear()


class DummyConfig(Config):
    @property
    @override
    def exchange(self) -> str:
        return "exchange_test"

    @property
    @override
    def queue(self) -> str:
        return "queue_test"

    @property
    @override
    def routing_key(self) -> str:
        return "routing.key.test"
