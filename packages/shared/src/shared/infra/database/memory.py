from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from shared.settings import settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(settings.REDIS_DSN, decode_responses=True)


RedisDep = Annotated[Redis, Depends(get_redis)]
