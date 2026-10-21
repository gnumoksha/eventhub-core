import json
from typing import Self, override

import pytest
from libs.events.encoding import JsonDecoder, JsonEncoder, UnmappedEventError
from libs.events.event import Metadata, PublishableEvent, SerializableDict


class EncodableEvent(PublishableEvent, name="test.encodable_event"):
    def __init__(self, key: str, count: int, metadata: Metadata | None = None) -> None:
        super().__init__(metadata)
        self.key = key
        self.count = count

    @override
    def to_dict(self) -> SerializableDict:
        return {"key": self.key, "count": self.count}

    @override
    @classmethod
    def from_dict(cls, payload: SerializableDict, metadata: Metadata) -> Self:
        return cls(str(payload["key"]), int(str(payload["count"])), metadata)


class TestEncoding:
    def test_encode_event_to_json(self):
        event = EncodableEvent("alpha", 42)
        encoder = JsonEncoder()

        encoded = encoder.encode(event)
        assert isinstance(encoded, str)

        parsed = json.loads(encoded)
        assert parsed["name"] == "test.encodable_event"
        assert parsed["metadata"]["id"] == str(event.metadata.id)
        assert parsed["metadata"]["schema_version"] == "1.0.0"
        assert parsed["payload"] == {"key": "alpha", "count": 42}

    def test_decode_from_json_string(self):
        event = EncodableEvent("beta", 99)
        encoder = JsonEncoder()
        decoder = JsonDecoder()

        encoded = encoder.encode(event)
        decoded = decoder.decode(encoded)

        assert isinstance(decoded, EncodableEvent)
        assert decoded.NAME == "test.encodable_event"
        assert decoded.key == "beta"
        assert decoded.count == 99
        assert decoded.metadata.id == event.metadata.id

    def test_decode_from_json_bytes(self):
        event = EncodableEvent("gamma", 100)
        encoder = JsonEncoder()
        decoder = JsonDecoder()

        encoded_bytes = encoder.encode(event).encode("utf-8")
        decoded = decoder.decode(encoded_bytes)

        assert isinstance(decoded, EncodableEvent)
        assert decoded.key == "gamma"
        assert decoded.count == 100

    def test_decode_unmapped_event_raises_unmapped_event_error(self):
        decoder = JsonDecoder()
        payload = json.dumps(
            {
                "name": "test.unknown_unregistered_event",
                "metadata": {
                    "id": "018f3a3d-42e8-78c6-bf41-47fb2ef9e31d",
                    "occurred_on": "2025-01-01T10:00:00+00:00",
                    "schema_version": "1.0.0",
                },
                "payload": {},
            }
        )

        with pytest.raises(UnmappedEventError, match="test.unknown_unregistered_event") as exc_info:
            decoder.decode(payload)

        assert exc_info.value.event_name == "test.unknown_unregistered_event"
        # it explains the obsolete binding cause, which can only be fixed manually
        assert "obsolete binding" in str(exc_info.value)
        assert "remove it manually" in str(exc_info.value)
