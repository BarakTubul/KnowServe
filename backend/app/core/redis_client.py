# app/core/redis_client.py
import asyncio

async def init_redis():
    """Mock Redis connection setup."""
    await asyncio.sleep(0.1)
    print("✅ [Mock] Redis connected.")

async def close_redis():
    """Mock Redis connection close."""
    await asyncio.sleep(0.1)
    print("🛑 [Mock] Redis connection closed.")
