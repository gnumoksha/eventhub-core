"""
Value objects for service's Inputs and Outputs.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field

from events.domain.models.event.event import Event
from events.domain.models.event.values import (
    Address,
    AgeRating,
    EventPeriod,
    EventStatus,
    OnlineVenue,
    PhysicalVenue,
    Venue,
)


class AddressSchema(BaseModel):
    street: str = Field(max_length=200)
    number: str = Field(max_length=20)
    complement: str | None = Field(default=None, max_length=100)
    district: str = Field(max_length=100)
    city: str = Field(max_length=100)
    state: str = Field(min_length=2, max_length=2, examples=["SP"])
    postal_code: str = Field(max_length=9, examples=["01310-100"])
    country: Literal["BR"] = "BR"


class PhysicalVenueSchema(BaseModel):
    type: Literal["physical"] = "physical"
    name: str = Field(max_length=200)
    address: AddressSchema

    def to_domain(self) -> PhysicalVenue:
        return PhysicalVenue(name=self.name, address=Address(**self.address.model_dump()))


class OnlineVenueSchema(BaseModel):
    type: Literal["online"] = "online"
    url: str = Field(max_length=500, examples=["https://meet.example.com/my-event"])

    def to_domain(self) -> OnlineVenue:
        return OnlineVenue(url=self.url)


VenueSchema = Annotated[PhysicalVenueSchema | OnlineVenueSchema, Field(discriminator="type")]


class PeriodSchema(BaseModel):
    start_at: AwareDatetime
    end_at: AwareDatetime

    def to_domain(self) -> EventPeriod:
        return EventPeriod(start_at=self.start_at, end_at=self.end_at)


class CreateEventInput(BaseModel):
    title: str = Field(max_length=100)
    description: str = Field(default="", max_length=10_000)
    age_rating: AgeRating = AgeRating.ALL_AGES
    venue: VenueSchema | None = None
    period: PeriodSchema | None = None


class UpdateEventDetailsInput(BaseModel):
    title: str = Field(max_length=100)
    description: str = Field(max_length=10_000)
    age_rating: AgeRating


class CancelEventInput(BaseModel):
    reason: str = Field(max_length=500)


class EventOutput(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    description: str
    age_rating: AgeRating
    status: EventStatus
    venue: VenueSchema | None
    period: PeriodSchema | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    banner_url: str | None = None

    @classmethod
    def from_domain(cls, event: Event, *, banner_url: str | None = None) -> EventOutput:
        return cls(
            id=event.id,
            organization_id=event.organization_id,
            title=event.title,
            description=event.description,
            age_rating=event.age_rating,
            status=event.status,
            venue=_venue_to_schema(event.venue),
            period=PeriodSchema(start_at=event.period.start_at, end_at=event.period.end_at) if event.period else None,
            cancellation_reason=event.cancellation_reason,
            created_at=event.created_at,
            updated_at=event.updated_at,
            banner_url=banner_url,
        )


def _venue_to_schema(venue: Venue | None) -> PhysicalVenueSchema | OnlineVenueSchema | None:
    match venue:
        case None:
            return None
        case OnlineVenue(url=url):
            return OnlineVenueSchema(url=url)
        case PhysicalVenue(name=name, address=address):
            return PhysicalVenueSchema(
                name=name,
                address=AddressSchema(
                    street=address.street,
                    number=address.number,
                    complement=address.complement,
                    district=address.district,
                    city=address.city,
                    state=address.state,
                    postal_code=address.postal_code,
                ),
            )
