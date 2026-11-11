import uuid
from datetime import UTC, datetime

from events.domain.models.event_view.event_view import EventView


def test_create_event_view_defaults():
    event_id = uuid.uuid4()
    before = datetime.now(UTC)
    view = EventView.record(event_id=event_id, visitor_hash="abc123hash")
    after = datetime.now(UTC)

    assert view.id is not None
    assert view.event_id == event_id
    assert view.visitor_hash == "abc123hash"
    assert before <= view.viewed_at <= after


def test_create_event_view_custom_timestamp():
    event_id = uuid.uuid4()
    custom_time = datetime(2028, 5, 20, 15, 30, tzinfo=UTC)
    view = EventView.record(
        event_id=event_id,
        visitor_hash="hashxyz",
        viewed_at=custom_time,
    )

    assert view.event_id == event_id
    assert view.visitor_hash == "hashxyz"
    assert view.viewed_at == custom_time
