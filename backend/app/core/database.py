# app/core/database.py
import asyncio

async def init_db():
    """Mock DB connection setup."""
    await asyncio.sleep(0.1)
    print("✅ [Mock] Database connected.")

async def close_db():
    """Mock DB close."""
    await asyncio.sleep(0.1)
    print("🛑 [Mock] Database connection closed.")
