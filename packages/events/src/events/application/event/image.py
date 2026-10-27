import json
from typing import Annotated, BinaryIO

import boto3
from botocore.client import BaseClient, Config
from fastapi.concurrency import run_in_threadpool
from shared.infra.di import Depends
from shared.settings import Settings, SettingsDep


class EventImageService:
    """Uploads event images to the configured S3-compatible storage."""

    def __init__(self, settings: Settings, s3_client: BaseClient | None = None) -> None:
        self._settings = settings
        self._s3_client = s3_client or boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION_NAME,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

    async def upload(
        self,
        image: BinaryIO,
        object_key: str,
        *,
        content_type: str | None = None,
    ) -> str:
        """Upload an image and return its object key."""
        return await run_in_threadpool(self._upload, image, object_key, content_type)

    def _upload(self, image: BinaryIO, object_key: str, content_type: str | None) -> str:
        bucket_name = self._settings.S3_BUCKET_EVENT_IMAGES
        if self._settings.is_dev_or_staging():
            self._ensure_bucket(bucket_name)

        extra_args = {"ContentType": content_type} if content_type else None
        if extra_args:
            self._s3_client.upload_fileobj(
                image,
                bucket_name,
                object_key,
                ExtraArgs=extra_args,
            )
        else:
            self._s3_client.upload_fileobj(image, bucket_name, object_key)
        return object_key

    def _ensure_bucket(self, bucket_name: str) -> None:
        buckets = self._s3_client.list_buckets().get("Buckets", [])
        if not any(bucket["Name"] == bucket_name for bucket in buckets):
            create_bucket_args = {"Bucket": bucket_name}
            if self._settings.S3_REGION_NAME != "us-east-1":
                create_bucket_args["CreateBucketConfiguration"] = {"LocationConstraint": self._settings.S3_REGION_NAME}
            self._s3_client.create_bucket(**create_bucket_args)

        self._s3_client.put_bucket_policy(
            Bucket=bucket_name,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": "s3:GetObject",
                            "Resource": f"arn:aws:s3:::{bucket_name}/*",
                        }
                    ],
                }
            ),
        )


async def __get_service(settings: SettingsDep) -> EventImageService:
    return EventImageService(settings)


EventImageServiceDep = Annotated[EventImageService, Depends(__get_service)]
