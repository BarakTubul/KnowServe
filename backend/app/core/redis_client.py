# app/core/redis_client.py
import redis.asyncio as aioredis
from app.config import settings

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
