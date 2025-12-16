from app.core.vector_store import get_vector_store

# -----------------------------
# CONFIG
# -----------------------------
DOC_IDS = []          # ← leave empty to inspect ALL docs
BATCH_SIZE = 5
OUTPUT_FILE = "vector_store_audit.txt"


def get_all_doc_ids(collection) -> list[int]:
    """
    Extract all unique doc_ids from the vector store metadata.
    """
    result = collection.get(include=["metadatas"])
    metadatas = result.get("metadatas", [])

    doc_ids = {
        meta["doc_id"]
        for meta in metadatas
        if meta and "doc_id" in meta
    }

    return sorted(doc_ids)


def main():
    vector_store = get_vector_store()
    collection = vector_store._collection

    # 🔍 Decide which documents to inspect
    if DOC_IDS:
        doc_ids = DOC_IDS
        print(f"📄 Inspecting specified doc IDs: {doc_ids}")
    else:
        doc_ids = get_all_doc_ids(collection)
        print(f"📦 Inspecting ALL documents from vector store ({len(doc_ids)} docs)")

    if not doc_ids:
        print("⚠️ No documents found in vector store.")
        return

    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        for i in range(0, len(doc_ids), BATCH_SIZE):
            batch = doc_ids[i : i + BATCH_SIZE]

            f.write("\n" + "=" * 120 + "\n")
            f.write(f"BATCH {i // BATCH_SIZE + 1} — DOC IDS: {batch}\n")
            f.write("=" * 120 + "\n\n")

            for doc_id in batch:
                print(f"🔍 Reading chunks for doc_id={doc_id}")

                result = collection.get(
                    where={"doc_id": doc_id},
                    include=["documents", "metadatas"],
                )

                chunks = result.get("documents", [])

                f.write(f"\n--- DOCUMENT {doc_id} ({len(chunks)} chunks) ---\n\n")

                if not chunks:
                    f.write("[⚠️ NO CHUNKS FOUND]\n\n")
                    continue

                for idx, chunk in enumerate(chunks, start=1):
                    f.write(f"\n[CHUNK {idx}]\n")
                    f.write(chunk)
                    f.write("\n")

            f.flush()

            answer = input("\n👉 Move on to next batch? [y/N]: ").strip().lower()
            if answer != "y":
                print("🛑 Stopping inspection.")
                break

    print(f"\n📁 Output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
