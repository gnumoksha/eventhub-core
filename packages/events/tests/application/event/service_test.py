import uuid
from datetime import timedelta

import pytest
from events.application.event.service import EventNotFound, EventService
from events.domain.models.event.events import EventFinished, EventPublished
from events.domain.models.event.values import AgeRating, EventStatus, EventUpdate
from libs.time_utils import FakeClock

from tests.conftest import InMemoryEventRepository, make_period, make_venue

pytestmark = pytest.mark.asyncio


async def create_draft(service: EventService, organization_id: uuid.UUID | None = None):
    return await service.create(
        organization_id=organization_id or uuid.uuid4(),
        title="Festival",
        description="",
        age_rating=AgeRating.ALL_AGES,
        venue=make_venue(),
        period=make_period(),
    )


async def test_create_persists_a_draft(service: EventService, repository: InMemoryEventRepository):
    event = await create_draft(service)

    assert await repository.get(event.id) is event
    assert event.status == EventStatus.DRAFT


async def test_publish_stores_integration_event_in_the_outbox(
    service: EventService, repository: InMemoryEventRepository
):
    event = await create_draft(service)

    await service.publish(event.id)

    assert [type(e) for e in repository.outbox] == [EventPublished]


async def test_unknown_event_raises_not_found(service: EventService):
    with pytest.raises(EventNotFound):
        await service.publish(uuid.uuid4())


async def test_list_by_organization_filters_by_status(service: EventService):
    organization_id = uuid.uuid4()
    draft = await create_draft(service, organization_id)
    published = await create_draft(service, organization_id)
    await service.publish(published.id)
    await create_draft(service)  # another organization

    all_org_events, total = await service.list_by_organization(organization_id)
    assert {e.id for e in all_org_events} == {draft.id, published.id}
    assert total == 2

    published_events, pub_total = await service.list_by_organization(organization_id, status=EventStatus.PUBLISHED)
    assert [e.id for e in published_events] == [published.id]
    assert pub_total == 1


async def test_finish_ended_events(service: EventService, repository: InMemoryEventRepository, clock: FakeClock):
    ended = await create_draft(service)
    await service.publish(ended.id)
    not_published = await create_draft(service)
    assert ended.period is not None
    clock.dt = ended.period.end_at + timedelta(minutes=1)
    repository.outbox.clear()

    finished = await service.finish_ended_events()

    assert finished == 1
    assert ended.status == EventStatus.FINISHED
    assert not_published.status == EventStatus.DRAFT
    assert [type(e) for e in repository.outbox] == [EventFinished]


async def test_slug_generation_and_collision(service: EventService):
    org_id = uuid.uuid4()
    ev1 = await service.create(
        organization_id=org_id,
        title="Lollapalooza Brasil",
        description="Music festival",
        age_rating=AgeRating.AGE_16,
        venue=make_venue(),
        period=make_period(),
    )
    assert ev1.slug == "lollapalooza-brasil"

    ev2 = await service.create(
        organization_id=org_id,
        title="Lollapalooza Brasil",
        description="Another festival edition",
        age_rating=AgeRating.AGE_16,
        venue=make_venue(),
        period=make_period(),
    )
    assert ev2.slug == "lollapalooza-brasil-2"

    ev3 = await service.create(
        organization_id=org_id,
        title="Lollapalooza Brasil",
        description="Third edition",
        age_rating=AgeRating.AGE_16,
        venue=make_venue(),
        period=make_period(),
    )
    assert ev3.slug == "lollapalooza-brasil-3"


async def test_slug_lifecycle_draft_mutates_published_immutable(service: EventService):
    org_id = uuid.uuid4()
    event = await service.create(
        organization_id=org_id,
        title="Initial Draft Title",
        description="desc",
        age_rating=AgeRating.ALL_AGES,
        venue=make_venue(),
        period=make_period(),
    )
    assert event.slug == "initial-draft-title"

    # Updating title while in DRAFT recalculates slug
    updated_draft = await service.update(
        event.id,
        EventUpdate(
            title="Updated Draft Title",
            description=event.description,
            age_rating=event.age_rating,
            venue=event.venue,
            period=event.period,
        ),
    )
    assert updated_draft.slug == "updated-draft-title"

    # Publish the event
    await service.publish(event.id)

    # Updating title after publication keeps the slug unchanged
    updated_published = await service.update(
        event.id,
        EventUpdate(
            title="Brand New Published Title",
            description=event.description,
            age_rating=event.age_rating,
            venue=event.venue,
            period=event.period,
        ),
    )
    assert updated_published.title == "Brand New Published Title"
    assert updated_published.slug == "updated-draft-title"
