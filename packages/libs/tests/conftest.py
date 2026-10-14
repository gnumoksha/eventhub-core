from collections.abc import Iterator

import pytest
from libs.events.listener import _listeners


@pytest.fixture(autouse=True)
def clean_listeners() -> Iterator[None]:
    yield
    _listeners.clear()
