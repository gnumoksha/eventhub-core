import uuid
from datetime import UTC, datetime
from typing import Self, override

import pytest
from libs.events.event import Metadata, PublishableEvent, SerializableDict


class SampleEvent(PublishableEvent, name="test.sample_event"):
    def __init__(self, message: str, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.message = message

    @override
    def to_dict(self) -> SerializableDict:
        return {"message": self.message}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(str(payload["message"]), metadata)


class TestMetadata:
    def test_default_metadata_initialization(self):
        before = datetime.now(UTC)
        meta = Metadata()
        after = datetime.now(UTC)

        assert isinstance(meta.id, uuid.UUID)
        assert meta.id.version == 7
        assert before <= meta.occurred_on <= after

    def test_custom_metadata_initialization(self):
        custom_id = uuid.uuid4()
        custom_time = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        meta = Metadata(schema_version="2.1.0", id=custom_id, occurred_on=custom_time)

        assert meta.id == custom_id
        assert meta.occurred_on == custom_time

    def test_serialization_and_deserialization(self):
        meta = Metadata(schema_version="1.0.0")
        data = meta.to_dict()

        assert data["id"] == str(meta.id)
        assert data["occurred_on"] == meta.occurred_on.isoformat()
        assert data["schema_version"] == "1.0.0"

        restored = Metadata.from_dict(data)
        assert restored.id == meta.id
        assert restored.occurred_on == meta.occurred_on


class TestPublishableEvent:
    def test_valid_event_registration_and_lookup(self):
        assert SampleEvent.name() == "test.sample_event"
        assert PublishableEvent.for_name("test.sample_event") is SampleEvent

    def test_unregistered_event_name_raises_key_error(self):
        with pytest.raises(KeyError):
            PublishableEvent.for_name("test.non_existent_event")

    def test_empty_event_name_raises_value_error(self):
        with pytest.raises(ValueError, match="Event name can not be empty"):

            class _EmptyNameEvent(PublishableEvent, name=""):
                @override
                def to_dict(self) -> SerializableDict:
                    return {}

                @override
                @classmethod
                def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
                    return cls(metadata)

    def test_event_name_too_long_raises_value_error(self):
        too_long_name = "x" * 201
        with pytest.raises(ValueError, match="Event name must be up to 200 characters long"):

            class _TooLongNameEvent(PublishableEvent, name=too_long_name):
                @override
                def to_dict(self) -> SerializableDict:
                    return {}

                @override
                @classmethod
                def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
                    return cls(metadata)

    @pytest.mark.parametrize(
        "name",
        [
            "eventhub:sales:order.placed",
            "eventhub.sales.*",
            "eventhub.sales.#",
            "Eventhub.sales",
            "eventhub..sales",
            "x.",
        ],
    )
    def test_event_name_with_invalid_format_raises_value_error(self, name):
        with pytest.raises(ValueError, match="must be lowercase words"):

            class _InvalidNameEvent(PublishableEvent, name=name):
                @override
                def to_dict(self) -> SerializableDict:
                    return {}

                @override
                @classmethod
                def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
                    return cls(metadata)

    def test_event_default_and_custom_metadata(self):
        event = SampleEvent("hello")
        assert event.metadata is not None
        assert isinstance(event.metadata.id, uuid.UUID)

        custom_meta = Metadata(schema_version="3.0.0")
        event_with_custom = SampleEvent("world", metadata=custom_meta)
        assert event_with_custom.metadata is custom_meta
