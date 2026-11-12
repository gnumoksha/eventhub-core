from datetime import datetime
from typing import Annotated

from shared.domain.errors import ConcurrencyConflict
from shared.infra.database.sql import SessionDep
from shared.infra.di import Depends
from shared.infra.outbox import add_to_outbox
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import col, func, select

from events.domain.models.event.event import Event
from events.domain.models.event.slug import resolve_available_slug
from events.domain.models.event.values import EventID, EventStatus, OrganizationID
from events.domain.models.event_view.event_view import EventView


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: EventID) -> Event | None:
        return await self._session.get(Event, id)

    async def find_ids_by_ids(self, event_ids: set[EventID]) -> set[EventID]:
        existing_events_res = await self._session.execute(select(Event.id).where(col(Event.id).in_(event_ids)))
        return set(existing_events_res.scalars().all())

    async def save(self, event: Event) -> None:
        """
        Inserts or updates the event and, in the same transaction, stores its
        pending integration events to be published.

        Raises:
            ConcurrencyConflict: if the event was modified since it was loaded.
        """
        event_id = event.id  # read before a rollback expires the object, which would reload it from the database
        self._session.add(event)
        # same transaction as the aggregate: the events are published if, and only if, the change is committed
        add_to_outbox(self._session, event.pull_events())

        try:
            await self._session.commit()
        except StaleDataError as exc:
            await self._session.rollback()
            raise ConcurrencyConflict(f"Event {event_id} was modified by someone else") from exc

    async def find_available_slug(self, base_slug: str, exclude_event_id: EventID | None = None) -> str:
        escaped_base = base_slug.replace("%", r"\%").replace("_", r"\_")
        query = select(Event.slug).where(col(Event.slug).like(f"{escaped_base}%"))
        if exclude_event_id is not None:
            query = query.where(col(Event.id) != exclude_event_id)
        result = await self._session.execute(query)
        existing_slugs = set(result.scalars().all())

        return resolve_available_slug(base_slug, existing_slugs)

    async def list_by_organization(
        self,
        organization_id: OrganizationID,
        *,
        status: EventStatus | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[Event], int]:
        filters = [Event.organization_id == organization_id]
        if status is not None:
            filters.append(Event.status == status)

        count_query = select(func.count(col(Event.id))).where(*filters)
        total_res = await self._session.execute(count_query)
        total = total_res.scalar_one_or_none() or 0

        query = (
            select(Event)
            .where(*filters)
            .order_by(col(Event.start_at).desc().nulls_first(), col(Event.id).desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self._session.execute(query)
        return list(result.scalars().all()), total

    async def list_public(
        self,
        now: datetime,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[Event], int]:
        filters = [
            col(Event.status).in_([EventStatus.PUBLISHED, EventStatus.POSTPONED]),
            col(Event.end_at) >= now,
        ]

        count_query = select(func.count(col(Event.id))).where(*filters)
        total_res = await self._session.execute(count_query)
        total = total_res.scalar_one_or_none() or 0

        views_count = func.count(col(EventView.id)).label("views_count")
        query = (
            select(Event)
            .outerjoin(EventView, col(Event.id) == col(EventView.event_id))
            .where(*filters)
            .group_by(col(Event.id))
            .order_by(
                views_count.desc(),
                col(Event.start_at).asc().nulls_last(),
                col(Event.id).asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all()), total

    async def list_ended_but_not_finished(self, now: datetime, *, limit: int) -> list[Event]:
        """Returns published or postponed events whose period already ended."""
        query = (
            select(Event)
            .where(
                col(Event.status).in_([EventStatus.PUBLISHED, EventStatus.POSTPONED]),
                col(Event.end_at) <= now,
            )
            .order_by(col(Event.end_at))
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())


async def __get_repository(session: SessionDep) -> EventRepository:
    return EventRepository(session)


EventRepositoryDep = Annotated[EventRepository, Depends(__get_repository)]
