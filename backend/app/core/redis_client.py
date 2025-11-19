# app/core/redis_client.py
import redis.asyncio as aioredis
import redis
from app.config import settings
import json
from typing import Any, Optional

# Global Redis connection instance
redis_client: aioredis.Redis | None = None


async def init_redis():
    """Initialize a Redis connection using REDIS_URL from settings."""
    global redis_client
    redis_url = settings.REDIS_URL or "redis://localhost:6379"

    try:
        redis_client = aioredis.from_url(
            redis_url,
            decode_responses=True,   # Return str instead of bytes
            health_check_interval=30 # Periodic ping
        )
        # Test the connection
        await redis_client.ping()
        print(f"✅ Connected to Redis at {redis_url}")
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        redis_client = None


async def close_redis():
    """Gracefully close the Redis connection."""
    global redis_client
    if redis_client:
        await redis_client.close()
        print("🛑 Redis connection closed.")


# ------------------------------------------------------------
# 🔹 Set cache value
# ------------------------------------------------------------
async def set_cache(key: str, value: Any, expire_seconds: int = 1800) -> bool:
    """
    Store a Python object (dict, list, etc.) in Redis as JSON.
    Args:
        key: Redis key name (e.g. "docs:department:2")
        value: Any JSON-serializable Python object
        expire_seconds: Expiration time in seconds (default 30 min)
    """
    global redis_client
    if not redis_client:
        print("⚠️ Redis client not initialized. Skipping cache set.")
        return False

    try:
        data = json.dumps(value)
        await redis_client.set(key, data, ex=expire_seconds)
        return True
    except Exception as e:
        print(f"❌ Failed to set cache for key '{key}': {e}")
        return False


# ------------------------------------------------------------
# 🔹 Get cache value
# ------------------------------------------------------------
async def get_cache(key: str) -> Optional[Any]:
    """
    Retrieve and decode a cached value from Redis.
    Args:
        key: Redis key name
    Returns:
        The decoded Python object, or None if not found / error.
    """
    global redis_client
    if not redis_client:
        print("⚠️ Redis client not initialized. Skipping cache get.")
        return None

    try:
        data = await redis_client.get(key)
        if data is None:
            return None
        return json.loads(data)
    except Exception as e:
        print(f"❌ Failed to get cache for key '{key}': {e}")
        return None

# ------------------------------------------------------------
# 🔹 delete cache value
# ------------------------------------------------------------
async def delete_cache(key: str) -> bool:
    """
    Delete a cache entry by key.
    Args:
        key: Redis key name (e.g. "docs:all")
    Returns:
        True if deleted, False otherwise.
    """
    global redis_client
    if not redis_client:
        print("⚠️ Redis client not initialized. Skipping cache delete.")
        return False

    try:
        result = await redis_client.delete(key)
        if result == 1:
            print(f"🗑️ Deleted cache key '{key}'")
            return True
        else:
            print(f"⚠️ Cache key '{key}' not found.")
            return False
    except Exception as e:
        print(f"❌ Failed to delete cache for key '{key}': {e}")
        return False

# ------------------------------------------------------------
# 🔹 invalidate cache values
# ------------------------------------------------------------
async def invalidate_caches(keys: list[str]):
    """
    Delete multiple cache keys using delete_cache().
    Args:
        keys: List of Redis keys to delete.
    """
    if not keys:
        print("⚠️ No cache keys provided to invalidate.")
        return

    deleted_count = 0
    for key in keys:
        success = await delete_cache(key)
        if success:
            deleted_count += 1

    print(f"🧹 [Redis] Invalidated {deleted_count}/{len(keys)} cache keys.")

def get_sync_redis():
    """
    Return a synchronous Redis client for use in Celery workers or sync contexts.
    This avoids 'NoneType' errors when the global async client isn't initialized.
    """
    redis_url = settings.REDIS_URL or "redis://localhost:6379"
    return redis.Redis.from_url(redis_url, decode_responses=True)


async def get_async_redis() -> aioredis.Redis:
    """
    Return a ready-to-use async Redis client.
    If the global redis_client isn't initialized, create a temporary one.
    """
    global redis_client
    if redis_client is None:
        redis_url = settings.REDIS_URL or "redis://localhost:6379"
        redis_client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            health_check_interval=30
        )
        try:
            await redis_client.ping()
            print(f"🔄 [Redis] Auto-initialized async client at {redis_url}")
        except Exception as e:
            print(f"❌ [Redis] Failed to auto-initialize: {e}")
    return redis_client

def publish_sync(channel: str, event: dict):
    """
    Publish an event to a Redis channel using a sync connection.
    Intended for Celery or any non-async context.
    """
    client = get_sync_redis()
    import json
    client.publish(channel, json.dumps(event))
    client.close()