"""Distributed lock abstractions and a Redis-backed implementation."""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from types import TracebackType
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from shared.infra.database.memory import AsyncRedisDatabase


class LockNotAcquiredError(Exception):
    """Raised when a lock cannot be acquired within a context manager."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Could not acquire lock for key: {key}")


class Lock(ABC):
    """A distributed lock handle.

    Not acquired on creation; call ``acquire()`` or use it as a context
    manager. As a context manager it raises :class:`LockNotAcquiredError` when
    the lock cannot be obtained.
    """

    @property
    @abstractmethod
    def acquired(self) -> bool:
        """Whether this instance currently holds the lock."""

    @abstractmethod
    async def acquire(self) -> bool:
        """Attempt to acquire the lock, returning True if now held."""

    @abstractmethod
    async def release(self) -> bool:
        """Release the lock if held, returning True if this call released it."""

    @abstractmethod
    async def __aenter__(self) -> Lock: ...

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class LockFactory(ABC):
    """Interface for creating distributed locks."""

    @abstractmethod
    def lock(
        self,
        key: str,
        *,
        ttl_seconds: int = 30,
        blocking: bool = False,
        timeout_seconds: float | None = None,
        retry_interval_seconds: float = 0.1,
    ) -> Lock:
        """Create an unacquired lock for ``key``."""


class RedisLock(Lock):
    """A distributed lock backed by Redis.

    Acquisition uses ``SET key <token> NX EX <ttl>`` so only one holder can own
    the lock at a time, and a TTL guarantees the lock is eventually released
    even if the holder crashes. Each instance owns a unique token; release is a
    compare-and-delete so a holder never deletes a lock that expired and was
    re-acquired by someone else.

    Usage as an asynchronous context manager (raises if it cannot acquire)::

        async with redis_client.lock("my-job", ttl_seconds=60):
            do_work()

    Usage with explicit control (no exception)::

        lock = redis_client.lock("my-job", ttl_seconds=60)
        if await lock.acquire():
            try:
                do_work()
            finally:
                await lock.release()
    """

    def __init__(  # noqa: PLR0913
        self,
        client: AsyncRedisDatabase,
        key: str,
        *,
        ttl_seconds: int = 30,
        blocking: bool = False,
        timeout_seconds: float | None = None,
        retry_interval_seconds: float = 0.1,
    ):
        self._client = client
        self._key = key
        self._ttl_seconds = ttl_seconds
        self._blocking = blocking
        self._timeout_seconds = timeout_seconds
        self._retry_interval_seconds = retry_interval_seconds
        self._token = uuid.uuid4().hex
        self._acquired = False

    @property
    @override
    def acquired(self) -> bool:
        """Whether this instance currently holds the lock."""
        return self._acquired

    @override
    async def acquire(self) -> bool:
        """Attempt to acquire the lock.

        When the lock was created with ``blocking=True``, retries every
        ``retry_interval_seconds`` until it succeeds or ``timeout_seconds``
        elapses. Otherwise makes a single attempt.

        Returns:
            True if the lock is now held by this instance, False otherwise.
        """
        deadline = None
        if self._blocking and self._timeout_seconds is not None:
            deadline = time.monotonic() + self._timeout_seconds

        while True:
            if await self._client.set_nx(self._key, self._token, ex=self._ttl_seconds):
                self._acquired = True
                return True

            if not self._blocking:
                return False

            if deadline is not None and time.monotonic() >= deadline:
                return False

            await asyncio.sleep(self._retry_interval_seconds)

    @override
    async def release(self) -> bool:
        """Release the lock if (and only if) this instance still holds it.

        Returns:
            True if the lock was released by this call, False otherwise.
        """
        if not self._acquired:
            return False
        released = await self._client.compare_and_delete(self._key, self._token)
        self._acquired = False
        return released

    @override
    async def __aenter__(self) -> RedisLock:
        if not await self.acquire():
            raise LockNotAcquiredError(self._key)
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()
