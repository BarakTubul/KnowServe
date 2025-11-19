# app/tasks/ingestion_task.py
from app.core.celery_app import celery_app
from app.services.ingestion_service import DocumentIngestionService
from app.core.redis_client import publish_sync

@celery_app.task(name="app.tasks.ingestion_task.run_ingestion_task")
def run_ingestion_task(doc_id: int, source_url: str, department_ids: list[int]):
    print(f"🚀 [Celery] Starting ingestion for doc {doc_id}")

    try:
        DocumentIngestionService.ingest_from_url_sync(doc_id, source_url)
        event = {"doc_id": doc_id, "status": "ingested", "departments": department_ids}
        publish_sync("ingestion_complete", event)
        print(f"✅ [Redis] Published ingestion_complete for doc {doc_id}")

    except Exception as e:
        event = {"doc_id": doc_id, "status": "failed", "error": str(e), "departments": department_ids}
        publish_sync("ingestion_failed", event)
        print(f"❌ [Redis] Published ingestion_failed for doc {doc_id}: {e}")
