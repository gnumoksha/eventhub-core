from datetime import UTC, datetime, timedelta, timezone

import pytest
from events.domain.models.event.event import Event
from events.domain.models.event.events import EventCancelled, EventFinished, EventPostponed, EventPublished
from events.domain.models.event.values import Address, AgeRating, EventPeriod, EventStatus, OnlineVenue
from shared.domain.errors import InvalidStateTransition, InvalidValue

from tests.conftest import NOW, make_draft, make_period, make_published, make_venue


class TestValueObjects:
    def test_period_must_end_after_it_starts(self):
        with pytest.raises(InvalidValue):
            EventPeriod(start_at=NOW, end_at=NOW)

    def test_period_requires_timezone_aware_datetimes(self):
        with pytest.raises(InvalidValue):
            EventPeriod(start_at=datetime(2030, 1, 1), end_at=datetime(2030, 1, 2))  # noqa: DTZ001

    def test_period_is_normalized_to_utc(self):
        brt = timezone(timedelta(hours=-3))
        period = EventPeriod(start_at=datetime(2030, 1, 1, 20, tzinfo=brt), end_at=datetime(2030, 1, 1, 23, tzinfo=brt))

        assert period.start_at == datetime(2030, 1, 1, 23, tzinfo=UTC)
        assert period.start_at.tzinfo == UTC

    def test_address_normalizes_postal_code_and_state(self):
        address = make_venue().address

        assert address.postal_code == "05001200"
        assert address.state == "SP"

    @pytest.mark.parametrize(("postal_code", "state"), [("123", "SP"), ("05001-200", "São Paulo")])
    def test_address_rejects_invalid_values(self, postal_code: str, state: str):
        with pytest.raises(InvalidValue):
            Address(street="Rua A", number="1", district="Centro", city="SP", state=state, postal_code=postal_code)

    def test_online_venue_requires_https(self):
        with pytest.raises(InvalidValue):
            OnlineVenue(url="http://example.com")


class TestCreate:
    def test_creates_a_draft(self):
        event = make_draft()

        assert event.status == EventStatus.DRAFT
        assert event.version == 0
        assert event.pull_events() == []

    @pytest.mark.parametrize("title", ["", "   ", "x" * 101])
    def test_rejects_invalid_titles(self, title: str):
        with pytest.raises(InvalidValue):
            Event.create(
                organization_id=make_draft().organization_id,
                title=title,
                description="",
                age_rating=AgeRating.ALL_AGES,
                now=NOW,
            )


class TestEditing:
    def test_draft_can_change_venue_and_period(self):
        event = make_draft()
        venue = OnlineVenue(url="https://meet.example.com/abc")
        period = make_period(days_from_now=60)

        event.change_venue(venue, NOW)
        event.schedule(period, NOW)

        assert event.venue == venue
        assert event.period == period

    def test_published_event_locks_venue_and_period(self):
        event = make_published()

        with pytest.raises(InvalidStateTransition):
            event.change_venue(OnlineVenue(url="https://meet.example.com/abc"), NOW)
        with pytest.raises(InvalidStateTransition):
            event.schedule(make_period(days_from_now=60), NOW)

    def test_published_event_can_update_details(self):
        event = make_published()
        later = NOW + timedelta(hours=1)

        event.update_details(title="New title", description="New", age_rating=AgeRating.AGE_18, now=later)

        assert event.title == "New title"
        assert event.age_rating == AgeRating.AGE_18
        assert event.updated_at == later

    def test_cancelled_event_cannot_be_edited(self):
        event = make_draft()
        event.cancel("Not happening", NOW)

        with pytest.raises(InvalidStateTransition):
            event.update_details(title="x", description="", age_rating=AgeRating.ALL_AGES, now=NOW)


class TestPublish:
    def test_publishes_and_records_event(self):
        event = make_draft()

        event.publish(NOW)

        assert event.status == EventStatus.PUBLISHED
        [published] = event.pull_events()
        assert isinstance(published, EventPublished)
        assert published.event_id == event.id
        assert event.period is not None
        assert published.start_at == event.period.start_at

    def test_requires_venue(self):
        with pytest.raises(InvalidStateTransition, match="venue"):
            make_draft(with_venue=False).publish(NOW)

    def test_requires_period(self):
        with pytest.raises(InvalidStateTransition, match="period"):
            make_draft(with_period=False).publish(NOW)

    def test_rejects_event_that_already_started(self):
        event = make_draft()
        assert event.period is not None

        with pytest.raises(InvalidStateTransition):
            event.publish(event.period.start_at)

    def test_cannot_publish_twice(self):
        with pytest.raises(InvalidStateTransition):
            make_published().publish(NOW)


class TestPostpone:
    def test_postpones_and_records_previous_period(self):
        event = make_published()
        previous = event.period
        assert previous is not None
        new_period = make_period(days_from_now=90)

        event.postpone(new_period, NOW)

        assert event.status == EventStatus.POSTPONED
        assert event.period == new_period
        [postponed] = event.pull_events()
        assert isinstance(postponed, EventPostponed)
        assert postponed.previous_start_at == previous.start_at
        assert postponed.start_at == new_period.start_at

    def test_can_postpone_again(self):
        event = make_published()
        event.postpone(make_period(days_from_now=60), NOW)

        event.postpone(make_period(days_from_now=90), NOW)

        assert event.status == EventStatus.POSTPONED

    def test_new_period_must_start_later(self):
        with pytest.raises(InvalidStateTransition):
            make_published().postpone(make_period(days_from_now=10), NOW)

    def test_draft_cannot_be_postponed(self):
        with pytest.raises(InvalidStateTransition):
            make_draft().postpone(make_period(days_from_now=90), NOW)


class TestCancel:
    def test_cancelling_a_published_event_notifies_other_contexts(self):
        event = make_published()

        event.cancel("  Artist is sick  ", NOW)

        assert event.status == EventStatus.CANCELLED
        assert event.cancellation_reason == "Artist is sick"
        [cancelled] = event.pull_events()
        assert isinstance(cancelled, EventCancelled)
        assert cancelled.reason == "Artist is sick"

    def test_cancelling_a_draft_does_not_record_events(self):
        event = make_draft()

        event.cancel("Changed my mind", NOW)

        assert event.status == EventStatus.CANCELLED
        assert event.pull_events() == []

    def test_requires_reason(self):
        with pytest.raises(InvalidValue):
            make_published().cancel("  ", NOW)

    def test_cannot_cancel_twice(self):
        event = make_published()
        event.cancel("reason", NOW)

        with pytest.raises(InvalidStateTransition):
            event.cancel("reason", NOW)


class TestFinish:
    def test_finishes_after_the_end(self):
        event = make_published()
        assert event.period is not None

        event.finish(event.period.end_at)

        assert event.status == EventStatus.FINISHED
        [finished] = event.pull_events()
        assert isinstance(finished, EventFinished)

    def test_cannot_finish_before_the_end(self):
        event = make_published()
        assert event.period is not None

        with pytest.raises(InvalidStateTransition):
            event.finish(event.period.end_at - timedelta(seconds=1))

    def test_cancelled_event_cannot_be_finished(self):
        event = make_published()
        event.cancel("reason", NOW)

        with pytest.raises(InvalidStateTransition):
            event.finish(NOW + timedelta(days=365))


class TestIntegrationEventsSerialization:
    def test_round_trip(self):
        event = make_published()
        event.postpone(make_period(days_from_now=90), NOW)
        event.cancel("reason", NOW)

        for recorded in event.pull_events():
            restored = type(recorded).from_dict(recorded.to_dict(), recorded.metadata)
            assert restored.to_dict() == recorded.to_dict()
