"""
Redis connection pool.

Replaces the SQLAlchemy/SQLite layer with a single async Redis client.
All data is stored in-memory by Redis — no disk DB files needed.
"""

import redis.asyncio as aioredis
from app.core.config import get_settings

settings = get_settings()

redis_pool: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    global redis_pool
    redis_pool = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
    await redis_pool.ping()
    return redis_pool


async def close_redis():
    global redis_pool
    if redis_pool:
        await redis_pool.aclose()
        redis_pool = None


def get_redis() -> aioredis.Redis:
    if redis_pool is None:
        raise RuntimeError("Redis not initialized — call init_redis() first")
    return redis_pool
