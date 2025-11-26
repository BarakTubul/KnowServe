# app/core/chroma_client.py

import os
from chromadb import PersistentClient
from app.config import settings

def get_chroma_client():
    """
    Creates a Chroma PersistentClient using an absolute path.
    Works for BOTH FastAPI and Celery workers.
    """

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
    return PersistentClient(path=chroma_dir)
