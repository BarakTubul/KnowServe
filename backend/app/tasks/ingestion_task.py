# app/tasks/ingestion_task.py
from app.services.ingestion_service import DocumentIngestionService

class IngestionTask:
    """Executes document ingestion asynchronously."""

    @staticmethod
    async def run_background(doc_id: int, url: str):
        try:
            print(f"🚀 Starting ingestion task for doc {doc_id}")
            await DocumentIngestionService.ingest_from_url(doc_id, url)
            print(f"✅ Completed ingestion for doc {doc_id}")
        except Exception as e:
            print(f"❌ Ingestion failed for doc {doc_id}: {e}")
