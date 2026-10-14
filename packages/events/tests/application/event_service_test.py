import uuid
from datetime import timedelta

import pytest
from events.application.event.service import EventNotFound, EventService
from events.domain.models.event.events import EventFinished, EventPublished
from events.domain.models.event.values import AgeRating, EventStatus
from libs.time_utils import FakeClock

from tests.conftest import InMemoryEventRepository, make_period, make_venue


def create_draft(service: EventService, organization_id: uuid.UUID | None = None):
    return service.create(
        organization_id=organization_id or uuid.uuid4(),
        title="Festival",
        description="",
        age_rating=AgeRating.ALL_AGES,
        venue=make_venue(),
        period=make_period(),
    )


def test_create_persists_a_draft(service: EventService, repository: InMemoryEventRepository):
    event = create_draft(service)

    assert repository.get(event.id) is event
    assert event.status == EventStatus.DRAFT


def test_publish_stores_integration_event_in_the_outbox(service: EventService, repository: InMemoryEventRepository):
    event = create_draft(service)

    service.publish(event.id)

    assert [type(e) for e in repository.outbox] == [EventPublished]


def test_unknown_event_raises_not_found(service: EventService):
    with pytest.raises(EventNotFound):
        service.publish(uuid.uuid4())


def test_list_by_organization_filters_by_status(service: EventService):
    organization_id = uuid.uuid4()
    draft = create_draft(service, organization_id)
    published = create_draft(service, organization_id)
    service.publish(published.id)
    create_draft(service)  # another organization

    assert {e.id for e in service.list_by_organization(organization_id)} == {draft.id, published.id}
    assert [e.id for e in service.list_by_organization(organization_id, status=EventStatus.PUBLISHED)] == [published.id]


def test_finish_ended_events(service: EventService, repository: InMemoryEventRepository, clock: FakeClock):
    ended = create_draft(service)
    service.publish(ended.id)
    not_published = create_draft(service)
    assert ended.period is not None
    clock.dt = ended.period.end_at + timedelta(minutes=1)
    repository.outbox.clear()

    finished = service.finish_ended_events()

    assert finished == 1
    assert ended.status == EventStatus.FINISHED
    assert not_published.status == EventStatus.DRAFT
    assert [type(e) for e in repository.outbox] == [EventFinished]
