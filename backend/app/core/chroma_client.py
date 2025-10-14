# app/core/chroma_client.py
from chromadb import PersistentClient
from app.config import settings
import os

# Global Chroma client instance
chroma_client = None


async def init_chroma():
    """Initialize the Chroma vector database."""
    global chroma_client
    chroma_path = settings.CHROMA_PATH or "chroma_data/"

    # Ensure the directory exists
    os.makedirs(chroma_path, exist_ok=True)

    try:
        chroma_client = PersistentClient(path=chroma_path)
        print(f"✅ Connected to Chroma at {chroma_path}")
    except Exception as e:
        print(f"❌ Failed to connect to Chroma: {e}")
        chroma_client = None


async def close_chroma():
    """Close the Chroma connection."""
    global chroma_client
    chroma_client = None
    print("🛑 Chroma client released.")
