# app/core/llama_vector_store.py
from app.core.chroma_client import get_chroma_client

# GLOBAL SINGLETON EMBEDDING MODEL
# This prevents the model from reloading from disk into RAM on every single query/tool call,
# which was causing a massive 20-30s delay in TTFT and retrieval latency.
_embed_model = None
_llama_index = None

def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        print("📥 [LlamaIndex] Loading Embedding Model (all-MiniLM-L6-v2)...")
        _embed_model = HuggingFaceEmbedding(model_name="all-MiniLM-L6-v2")
    return _embed_model

def get_llama_index():
    global _llama_index
    if _llama_index is not None:
        return _llama_index

    client = get_chroma_client()
    chroma_collection = client.get_or_create_collection("documents")
    
    embed_model = get_embed_model()
    
    from llama_index.vector_stores.chroma import ChromaVectorStore
    from llama_index.core import VectorStoreIndex
    
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    
    print("🧠 [LlamaIndex] Initializing VectorStoreIndex singleton...")
    _llama_index = VectorStoreIndex.from_vector_store(
        vector_store, 
        embed_model=embed_model
    )
    return _llama_index