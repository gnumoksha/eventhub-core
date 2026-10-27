import io
import json
from typing import BinaryIO, cast

import pytest
from botocore.client import BaseClient
from events.application.event.image import EventImageService
from shared.settings import Settings

pytestmark = pytest.mark.asyncio


class FakeS3Client:
    def __init__(self, existing_buckets: tuple[str, ...] = ()) -> None:
        self.buckets = set(existing_buckets)
        self.list_buckets_calls = 0
        self.created_buckets: list[dict[str, object]] = []
        self.bucket_policies: list[dict[str, str]] = []
        self.uploads: list[dict[str, object]] = []

    def list_buckets(self) -> dict[str, list[dict[str, str]]]:
        self.list_buckets_calls += 1
        return {"Buckets": [{"Name": name} for name in sorted(self.buckets)]}

    def create_bucket(self, **kwargs: object) -> None:
        self.created_buckets.append(kwargs)
        bucket_name = kwargs["Bucket"]
        assert isinstance(bucket_name, str)
        self.buckets.add(bucket_name)

    def put_bucket_policy(self, **kwargs: str) -> None:
        self.bucket_policies.append(kwargs)

    def upload_fileobj(
        self,
        image: BinaryIO,
        bucket_name: str,
        object_key: str,
        **kwargs: object,
    ) -> None:
        self.uploads.append(
            {
                "bucket": bucket_name,
                "key": object_key,
                "body": image.read(),
                "extra_args": kwargs.get("ExtraArgs"),
            }
        )


def make_settings(app_env: str, region: str = "us-east-1") -> Settings:
    return Settings.model_construct(
        APP_ENV=app_env,
        S3_ENDPOINT_URL="http://rustfs-server:9000",
        S3_REGION_NAME=region,
        S3_ACCESS_KEY="test-access-key",
        S3_SECRET_KEY="test-secret-key",  # noqa: S106
        S3_BUCKET_EVENT_IMAGES="event-images",
    )


async def test_upload_creates_missing_development_bucket_and_uploads_image() -> None:
    s3_client = FakeS3Client()
    service = EventImageService(
        make_settings("development"), cast(BaseClient, s3_client)
    )

    object_key = await service.upload(
        io.BytesIO(b"image-bytes"),
        "events/event-1/cover.png",
        content_type="image/png",
    )

    assert object_key == "events/event-1/cover.png"
    assert s3_client.created_buckets == [{"Bucket": "event-images"}]
    assert s3_client.uploads == [
        {
            "bucket": "event-images",
            "key": "events/event-1/cover.png",
            "body": b"image-bytes",
            "extra_args": {"ContentType": "image/png"},
        }
    ]
    policy = json.loads(s3_client.bucket_policies[0]["Policy"])
    assert policy["Statement"][0]["Action"] == "s3:GetObject"
    assert policy["Statement"][0]["Resource"] == "arn:aws:s3:::event-images/*"


async def test_upload_creates_bucket_in_configured_staging_region() -> None:
    s3_client = FakeS3Client()
    service = EventImageService(
        make_settings("staging", region="sa-east-1"),
        cast(BaseClient, s3_client),
    )

    await service.upload(io.BytesIO(b"image-bytes"), "events/event-1/cover.png")

    assert s3_client.created_buckets == [
        {
            "Bucket": "event-images",
            "CreateBucketConfiguration": {"LocationConstraint": "sa-east-1"},
        }
    ]


async def test_upload_does_not_recreate_existing_bucket() -> None:
    s3_client = FakeS3Client(existing_buckets=("event-images",))
    service = EventImageService(
        make_settings("development"), cast(BaseClient, s3_client)
    )

    await service.upload(io.BytesIO(b"image-bytes"), "events/event-1/cover.png")

    assert s3_client.list_buckets_calls == 1
    assert s3_client.created_buckets == []
    assert len(s3_client.bucket_policies) == 1
    assert len(s3_client.uploads) == 1


@pytest.mark.parametrize("app_env", ["test", "production"])
async def test_upload_does_not_check_or_create_bucket_outside_dev_and_staging(
    app_env: str,
) -> None:
    s3_client = FakeS3Client()
    service = EventImageService(make_settings(app_env), cast(BaseClient, s3_client))

    await service.upload(io.BytesIO(b"image-bytes"), "events/event-1/cover.png")

    assert s3_client.list_buckets_calls == 0
    assert s3_client.created_buckets == []
    assert s3_client.bucket_policies == []
    assert len(s3_client.uploads) == 1
