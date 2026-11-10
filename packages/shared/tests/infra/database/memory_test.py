from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from shared.infra.database.memory import AsyncRedisDatabase
from shared.settings import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app_env() -> str:
    return f"test_{uuid4().hex}"


@pytest_asyncio.fixture
async def redis(app_env: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.REDIS_DSN, decode_responses=True)

    try:
        await client.ping()
        yield client
    finally:
        keys = [key async for key in client.scan_iter(match=f"eventhub_{app_env}_*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


@pytest_asyncio.fixture
async def bytes_redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.REDIS_DSN, decode_responses=False)

    try:
        await client.ping()
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def database(redis: Redis, app_env: str) -> AsyncRedisDatabase:
    return AsyncRedisDatabase(redis, app_env=app_env)


async def test_set_stores_value_with_environment_prefix_and_expiration(
    database: AsyncRedisDatabase, redis: Redis, app_env: str
):
    result = await database.set("event:1", "cached", expiration=60)

    redis_key = f"eventhub_{app_env}_event:1"
    assert result is True
    assert await redis.get(redis_key) == "cached"
    assert 0 < await redis.ttl(redis_key) <= 60


async def test_get_returns_stored_value(database: AsyncRedisDatabase, redis: Redis, app_env: str):
    await redis.set(f"eventhub_{app_env}_event:1", "cached")

    assert await database.get("event:1") == "cached"


async def test_get_decodes_bytes_from_redis(
    database: AsyncRedisDatabase, bytes_redis: Redis, app_env: str, redis: Redis
):
    bytes_database = AsyncRedisDatabase(bytes_redis, app_env=app_env)
    await redis.set(f"eventhub_{app_env}_event:1", "cached")

    assert await bytes_database.get("event:1") == "cached"


async def test_get_returns_none_for_missing_key(database: AsyncRedisDatabase):
    assert await database.get("missing") is None


async def test_set_complex_stores_ascii_serialization_and_expiration(
    database: AsyncRedisDatabase, redis: Redis, app_env: str
):
    value = {"items": [1, 2, 3], "enabled": True}

    result = await database.set_complex("complex", value, expiration=120)

    redis_key = f"eventhub_{app_env}_complex"
    serialized = await redis.get(redis_key)
    assert result is True
    assert serialized is not None
    assert serialized.isascii()
    assert 0 < await redis.ttl(redis_key) <= 120


async def test_complex_value_round_trips_through_redis(database: AsyncRedisDatabase):
    value = {"items": [1, 2, 3], "enabled": True}
    assert await database.set_complex("complex", value)

    assert await database.get_complex("complex") == value


async def test_get_complex_returns_none_for_missing_key(database: AsyncRedisDatabase):
    assert await database.get_complex("missing") is None


async def test_delete_removes_key_and_returns_deleted_count(database: AsyncRedisDatabase):
    await database.set("event:1", "cached")

    assert await database.delete("event:1") == 1
    assert await database.delete("event:1") == 0
    assert await database.get("event:1") is None


async def test_set_nx_only_sets_value_when_key_is_absent(database: AsyncRedisDatabase):
    assert await database.set_nx("lock", "first-token", ex=30) is True
    assert await database.set_nx("lock", "second-token", ex=30) is False
    assert await database.get("lock") == "first-token"


async def test_compare_and_delete_only_deletes_matching_token(database: AsyncRedisDatabase):
    assert await database.set_nx("lock", "current-token", ex=30)

    assert await database.compare_and_delete("lock", "stale-token") is False
    assert await database.get("lock") == "current-token"
    assert await database.compare_and_delete("lock", "current-token") is True
    assert await database.get("lock") is None
