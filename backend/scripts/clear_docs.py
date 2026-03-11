from app.core.chroma_client import get_chroma_client

if __name__ == "__main__":
    client = get_chroma_client()
    client.delete_collection("documents")  # Delete the entire collection
    print("✅ Vector store cleared successfully")
