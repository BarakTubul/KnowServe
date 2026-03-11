import os
import uuid
import gdown
import pandas as pd
from app.core.vector_store import get_llama_index
from app.core.chroma_client import get_chroma_client
from app.services.ingestion_service import DocumentIngestionService
from llama_index.core.node_parser import SentenceSplitter


def ingest_from_csv():
    base_path = os.path.dirname(os.path.abspath(__file__))

    docs_path = os.path.join(base_path, "documents.csv")
    access_path = os.path.join(base_path, "department_documents_access.csv")

    # 1. Load CSVs
    docs_df = pd.read_csv(docs_path)
    access_df = pd.read_csv(access_path)

    # 2. Build permissions map
    permissions = (
        access_df.groupby("document_id")["department_id"]
        .apply(list)
        .to_dict()
    )

    try:
        client = get_chroma_client()
        client.delete_collection("documents")
        print("🗑️ Deleted old 'documents' collection from ChromaDB")
    except Exception as e:
        print(f"⚠️ Note on collection deletion: {e}")

    all_llama_nodes = []

    # good chunking for policy documents
    splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=120)

    for _, row in docs_df.iterrows():
        doc_id = int(row["id"])
        source_url = row["source_url"]
        allowed_depts = permissions.get(doc_id, [])

        if not allowed_depts:
            print(f"⚠️ Skipping doc {doc_id} ('{row['title']}'): No permissions defined.")
            continue

        print(f"🔄 Processing: {row['title']} (ID: {doc_id})...")

        try:
            metadata = {
                "db_doc_id": int(doc_id),
                "title": str(row["title"]),
            }

            # extract document pages
            llama_documents = DocumentIngestionService.extract_documents_from_url(
                source_url,
                metadata
            )

            # split into chunks
            nodes = splitter.get_nodes_from_documents(llama_documents)

            # Format described in the ingestion service: only db_doc_id is needed, no department info.
            for node in nodes:
                node.metadata.pop("allowed_dept_ids", None)
                node.metadata["db_doc_id"] = int(doc_id)

            all_llama_nodes.extend(nodes)

            print(f"✅ Generated {len(nodes)} chunks for '{row['title']}'")

        except Exception as e:
            print(f"❌ Failed to extract '{row['title']}': {e}")

    # 4. Insert into vector DB
    if all_llama_nodes:
        index = get_llama_index()
        index.insert_nodes(all_llama_nodes)

        print("\n🚀 VECTOR STORE REBUILT SUCCESSFULLY")
        print(f"Total nodes inserted: {len(all_llama_nodes)}")
        print("Permissions metadata stored as structured JSON (fixed).")


if __name__ == "__main__":
    ingest_from_csv()