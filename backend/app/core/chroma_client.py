# app/core/chroma_client.py

import os
from chromadb import PersistentClient
from app.config import settings



print("CHROMA_TELEMETRY =", os.getenv("CHROMA_TELEMETRY"))

_chroma_client = None

def get_chroma_client():
    """
    Creates a Chroma PersistentClient using an absolute path.
    Returns a global singleton to prevent reloading disk indexes on every call.
    """
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    chroma_host = os.getenv("CHROMA_HOST")
    chroma_port = os.getenv("CHROMA_PORT", "8000")

    if chroma_host:
        from chromadb import HttpClient
        print(f"Connecting to ChromaDB Server at {chroma_host}:{chroma_port}")
        _chroma_client = HttpClient(host=chroma_host, port=chroma_port)
        return _chroma_client

    from chromadb import PersistentClient
    # Base directory = backend/app
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Path to chroma_data folder (default: app/chroma_data)
    chroma_dir = os.path.join(
        base_dir,
        settings.CHROMA_PATH or "chroma_data"
    )

    # Ensure folder exists
    os.makedirs(chroma_dir, exist_ok=True)

    # Create real Chroma client pointing to the persistent directory
    _chroma_client = PersistentClient(path=chroma_dir)
    return _chroma_client
