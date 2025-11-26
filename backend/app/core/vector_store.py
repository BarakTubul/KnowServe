# app/core/vector_store.py

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from app.core.chroma_client import get_chroma_client

# One global embeddings instance (safe to share)
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"},
)

def get_vector_store(collection_name: str = "documents"):
    """
    Returns a LangChain Chroma vector store configured with:
    - same persistent storage
    - same embedding model
    - same collection name
    """

    client = get_chroma_client()

    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embeddings,
    )
