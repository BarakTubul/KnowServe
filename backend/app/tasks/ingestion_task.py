# app/tasks/ingestion_task.py
from app.core.celery_app import celery_app
from app.services.ingestion_service import DocumentIngestionService
from app.core.redis_client import redis_client


@celery_app.task(name="tasks.run_ingestion")
def run_ingestion_task(doc_id: int, source_url: str, department_ids: list[int]):
    """
    Run document ingestion in the background via Celery.
    """
    print(f"🚀 [Celery] Starting ingestion for doc {doc_id}")

    try:
        # Run the main ingestion pipeline (synchronous call)
        import asyncio
        asyncio.run(DocumentIngestionService.ingest_from_url(doc_id, source_url,department_ids))

    except Exception as e:
        print(f"❌ [Celery] Ingestion failed for doc {doc_id}: {e}")
        raise e  # keep trace in Celery logs
