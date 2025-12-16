import csv
from pathlib import Path

from app.services.ingestion_service import DocumentIngestionService

# -----------------------------
# CONFIG
# -----------------------------
CSV_PATH = Path(__file__).parent / "documents.csv"
CHECKPOINT_PATH = Path(__file__).parent / "ingest_checkpoint.txt"

SKIP_DOC_ID = 20
BATCH_SIZE = 5


def load_checkpoint() -> set[int]:
    if not CHECKPOINT_PATH.exists():
        return set()
    return {
        int(line.strip())
        for line in CHECKPOINT_PATH.read_text().splitlines()
        if line.strip().isdigit()
    }


def append_checkpoint(doc_id: int):
    with open(CHECKPOINT_PATH, "a", encoding="utf-8") as f:
        f.write(f"{doc_id}\n")


def main():
    print("📄 Starting ingestion from CSV (unsorted-safe, checkpointed)\n")

    ingested = load_checkpoint()
    if ingested:
        print(f"🔁 Resuming — {len(ingested)} docs already ingested\n")

    processed_in_batch = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            print("Row to ingest: ", row)
            # -------------------------
            # 1️⃣ Validate CSV schema
            # -------------------------
            if "id" not in row or "source_url" not in row:
                print("⚠️ CSV must contain doc_id and source_url columns")
                return

            doc_id = int(row["id"])
            source_url = row["source_url"]

            # -------------------------
            # 2️⃣ Skip logic
            # -------------------------
            if doc_id == SKIP_DOC_ID:
                print(f"⏭️ Skipping doc_id={doc_id}")
                continue

            if doc_id in ingested:
                continue

            # -------------------------
            # 3️⃣ Ingest
            # -------------------------
            print(f"🚀 Ingesting doc_id={doc_id}")

            try:
                DocumentIngestionService.ingest_from_url_sync(
                    doc_id=doc_id,
                    source_url=source_url,
                )

                print(f"✅ Ingested doc_id={doc_id}\n")

                # 4️⃣ Persist checkpoint
                append_checkpoint(doc_id)
                ingested.add(doc_id)
                processed_in_batch += 1

            except Exception as e:
                print(f"❌ Failed to ingest doc_id={doc_id}: {e}\n")
                print("🛑 Stopping to avoid skipping documents.")
                return

            # -------------------------
            # 5️⃣ Batch pause
            # -------------------------
            if processed_in_batch >= BATCH_SIZE:
                processed_in_batch = 0
                answer = input("👉 Continue with next batch? [y/N]: ").strip().lower()
                if answer != "y":
                    print("🛑 Stopping by user request.")
                    return

    print("🏁 CSV ingestion complete")


if __name__ == "__main__":
    main()
