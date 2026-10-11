# Value objects of the Event aggregate

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from shared.domain.errors import InvalidValue

EventID = uuid.UUID
OrganizationID = uuid.UUID


# The enum values are equal to their names because the database stores the names
# (see the Event columns), so the API returns exactly what is in the database.


class EventStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    FINISHED = "FINISHED"


class AgeRating(StrEnum):
    """Brazilian indicative rating (ClassInd)."""

    ALL_AGES = "ALL_AGES"
    AGE_10 = "AGE_10"
    AGE_12 = "AGE_12"
    AGE_14 = "AGE_14"
    AGE_16 = "AGE_16"
    AGE_18 = "AGE_18"


@dataclass(frozen=True, slots=True)
class EventPeriod:
    """When the event happens. A single period that may span several days."""

    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise InvalidValue("The event period must have timezone-aware datetimes")
        if self.end_at <= self.start_at:
            raise InvalidValue("The event must end after it starts")

        # normalize to UTC so that equality does not depend on the timezone used by the caller
        object.__setattr__(self, "start_at", self.start_at.astimezone(UTC))
        object.__setattr__(self, "end_at", self.end_at.astimezone(UTC))

    def has_started(self, now: datetime) -> bool:
        return now >= self.start_at

    def has_ended(self, now: datetime) -> bool:
        return now >= self.end_at


_POSTAL_CODE = re.compile(r"^\d{8}$")
_STATE = re.compile(r"^[A-Z]{2}$")


@dataclass(frozen=True, slots=True)
class Address:
    street: str
    number: str
    district: str
    city: str
    state: str
    postal_code: str
    complement: str | None = None
    country: str = "BR"

    def __post_init__(self) -> None:
        for field_name in ("street", "number", "district", "city"):
            if not getattr(self, field_name).strip():
                raise InvalidValue(f"The address {field_name} is required")

        postal_code = re.sub(r"\D", "", self.postal_code)
        if not _POSTAL_CODE.match(postal_code):
            raise InvalidValue("The postal code must have 8 digits")
        object.__setattr__(self, "postal_code", postal_code)

        state = self.state.strip().upper()
        if not _STATE.match(state):
            raise InvalidValue("The state must be a 2-letter code")
        object.__setattr__(self, "state", state)


@dataclass(frozen=True, slots=True)
class PhysicalVenue:
    name: str
    address: Address

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidValue("The venue name is required")


@dataclass(frozen=True, slots=True)
class OnlineVenue:
    url: str

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise InvalidValue("The online venue URL must use https")


Venue = PhysicalVenue | OnlineVenue
