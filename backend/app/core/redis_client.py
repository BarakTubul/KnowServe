# app/core/redis_client.py
import redis.asyncio as aioredis
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

