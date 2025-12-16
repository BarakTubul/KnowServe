from app.core.vector_store import get_vector_store

if __name__ == "__main__":
    vector_store = get_vector_store()
    vector_store.delete_collection()
    print("✅ Vector store cleared successfully")
