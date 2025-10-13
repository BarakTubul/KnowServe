# app/core/chroma_client.py
import asyncio

async def init_chroma():
    """Mock Chroma initialization."""
    await asyncio.sleep(0.1)
    print("✅ [Mock] Chroma connected.")

async def close_chroma():
    """Mock Chroma shutdown."""
    await asyncio.sleep(0.1)
    print("🛑 [Mock] Chroma connection closed.")
