import base64
import pickle
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Annotated, Any, override

from fastapi import Depends
from redis.asyncio import Redis
from redis.typing import ExpiryT
from shared.infra.lock import LockFactory, RedisLock
from shared.settings import SettingsDep


class AsyncCache(ABC):
    """Cache interface"""

    @abstractmethod
    async def set(self, key: str, value: str, expiration: ExpiryT | None = None) -> bool:
        """Set a key-value pair in the cache."""

    @abstractmethod
    async def set_complex(self, key: str, value: Any, expiration: ExpiryT | None = None) -> bool:
        """Set a key-value pair in the cache, where the value can be any serializable object."""

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Get the value associated with a key from the cache."""

    @abstractmethod
    async def get_complex(self, key: str) -> Any | None:
        """Get the value associated with a key from the cache, where the value can be any serializable object."""

    @abstractmethod
    async def delete(self, *keys: str) -> int:
        """Delete one or more keys from the cache."""

    @abstractmethod
    async def increment(self, key: str, amount: int = 1) -> int:
        """Atomically increment a counter."""

    @abstractmethod
    async def expire(self, key: str, expiration: ExpiryT) -> bool:
        """Set a key's expiration."""


class InMemoryAsyncCache(AsyncCache):
    """Cache implementation using a dictionary for testing purposes."""

    def __init__(self):
        self._cache: dict[str, Any] = {}

    @override
    async def set(self, key: str, value: str, expiration: ExpiryT | None = None) -> bool:
        self._cache[key] = value
        return True

    @override
    async def set_complex(self, key: str, value: Any, expiration: ExpiryT | None = None) -> bool:
        self._cache[key] = value
        return True

    @override
    async def get(self, key: str) -> str | None:
        return self._cache.get(key)

    @override
    async def get_complex(self, key: str) -> Any | None:
        return self._cache.get(key)

    @override
    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._cache:
                del self._cache[key]
                deleted += 1
        return deleted

    @override
    async def increment(self, key: str, amount: int = 1) -> int:
        raise NotImplementedError("InMemoryAsyncCache does not support incrementing counters.")

    @override
    async def expire(self, key: str, expiration: ExpiryT) -> bool:
        raise NotImplementedError("InMemoryAsyncCache does not support key expiration.")


class AsyncRedisDatabase(AsyncCache, LockFactory):
    """Cache implementation backed by an asynchronous Redis client."""

    def __init__(self, redis: Redis, app_env: str):
        self._redis = redis
        self.__app_env = app_env

    @override
    async def set(self, key: str, value: str, expiration: ExpiryT | None = None) -> bool:
        result = await self._redis.set(self._build_key(key), value, ex=expiration)
        return result is not None

    @override
    async def set_complex(self, key: str, value: Any, expiration: ExpiryT | None = None) -> bool:
        serialized = base64.b64encode(pickle.dumps(value)).decode("ascii")
        result = await self._redis.set(self._build_key(key), serialized, ex=expiration)
        return result is not None

    @override
    async def get(self, key: str) -> str | None:
        value = await self._redis.get(self._build_key(key))
        return value.decode() if isinstance(value, bytes) else value

    @override
    async def get_complex(self, key: str) -> Any | None:
        serialized = await self._redis.get(self._build_key(key))
        if serialized is None:
            return None

        value = base64.b64decode(serialized, validate=True)
        return pickle.loads(value)  # noqa: S301

    @override
    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return await self._redis.delete(*(self._build_key(key) for key in keys))

    @override
    async def increment(self, key: str, amount: int = 1) -> int:
        return await self._redis.incrby(self._build_key(key), amount)

    @override
    async def expire(self, key: str, expiration: ExpiryT) -> bool:
        return await self._redis.expire(self._build_key(key), expiration)

    @override
    def lock(
        self,
        key: str,
        *,
        ttl_seconds: int = 30,
        blocking: bool = False,
        timeout_seconds: float | None = None,
        retry_interval_seconds: float = 0.1,
    ) -> RedisLock:
        """Create a distributed lock backed by this Redis client.

        The returned lock is not acquired yet; call ``acquire()`` or use it as a
        context manager.

        Args:
            key: Lock key (will be namespaced).
            ttl_seconds: Auto-expiry for the lock, so a crashed holder never
                blocks others forever. Keep it comfortably above the expected
                critical-section duration.
            blocking: If True, ``acquire()`` retries until the lock is obtained
                or ``timeout_seconds`` elapses. If False, it returns immediately.
            timeout_seconds: Max time to wait when blocking (None = forever).
            retry_interval_seconds: Delay between acquisition attempts when blocking.

        Returns:
            An unacquired :class:`RedisLock`.
        """
        return RedisLock(
            self,
            key,
            ttl_seconds=ttl_seconds,
            blocking=blocking,
            timeout_seconds=timeout_seconds,
            retry_interval_seconds=retry_interval_seconds,
        )

    async def set_nx(self, key: str, value: str, *, ex: int) -> bool:
        """Set a key only if it does not already exist (atomic lock acquire).

        Args:
            key: The key to set.
            value: The value to set.
            ex: Expiration time in seconds (required to avoid orphaned locks).

        Returns:
            True if the key was set (lock acquired), False if it already existed.
        """

        result = await self._redis.set(self._build_key(key), value, ex=ex, nx=True)
        return result is not None

    async def compare_and_delete(self, key: str, expected_value: str) -> bool:
        """Atomically delete a key only if its current value matches.

        Used to release a distributed lock without risking the deletion of a
        lock re-acquired by another holder after the original TTL expired.

        Args:
            key: The key to delete (will be namespaced).
            expected_value: Only delete if the stored value equals this.

        Returns:
            True if the key was deleted, False otherwise.
        """

        # Atomically delete a key only if its value matches the caller's token.
        # This prevents a process from releasing a lock that has already expired and
        # been re-acquired by someone else.
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """

        deleted = await self._redis.eval(script, 1, self._build_key(key), expected_value)
        return bool(deleted)

    def _build_key(self, key: str) -> str:
        return f"eventhub_{self.__app_env}_{key}"


@lru_cache
def _get_redis(redis_dsn: str) -> Redis:
    # decode_responses=True makes Redis return strings instead of bytes.
    return Redis.from_url(redis_dsn, decode_responses=True)


def get_redis(settings: SettingsDep) -> Redis:
    return _get_redis(settings.REDIS_DSN)


@lru_cache
def _get_async_redis_database(redis_dsn: str, app_env: str) -> AsyncRedisDatabase:
    return AsyncRedisDatabase(_get_redis(redis_dsn), app_env=app_env)


def get_async_redis_database(settings: SettingsDep) -> AsyncRedisDatabase:
    return _get_async_redis_database(settings.REDIS_DSN, settings.APP_ENV)


RedisDep = Annotated[Redis, Depends(get_redis)]
AsyncCacheDep = Annotated[AsyncCache, Depends(get_async_redis_database)]
LockDep = Annotated[LockFactory, Depends(get_async_redis_database)]
