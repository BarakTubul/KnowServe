import asyncio, json
from app.core.redis_client import get_async_redis, invalidate_caches
from app.core.database import SessionLocal
from app.models.document import Document
from app.core.websocket_manager import manager

async def listen_for_ingestion_events():
    """Listen to Redis Pub/Sub events from Celery worker for ingestion results."""
    client = await get_async_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe("ingestion_complete", "ingestion_failed")
    print("📡 Listening for ingestion events...")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        data = json.loads(message["data"])
        doc_id = data["doc_id"]
        status = data.get("status", "unknown")
        department_ids = data.get("departments", [])  # ✅ safely extract list

        # ✅ Update PostgreSQL document status
        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = status
                db.commit()
                print(f"📘 [DB] Document {doc_id} status updated → '{status}'")
            else:
                print(f"⚠️ [DB] Document {doc_id} not found")
        except Exception as e:
            print(f"❌ [DB] Error updating document {doc_id}: {e}")
        finally:
            db.close()

        # 🧹 Invalidate Redis caches
        keys_to_invalidate = [f"docs:all", f"doc:{doc_id}"]
        for dep_id in department_ids:
            keys_to_invalidate.append(f"docs:department:{dep_id}")

        await invalidate_caches(keys_to_invalidate)
        print(f"🧹 [Ingestion] Cache invalidated for document {doc_id}")

        # 📡 Notify WebSocket clients
        message_text = (
            f"Ingestion {status} for document {doc_id}."
            if status != "failed"
            else f"Ingestion failed for document {doc_id}."
        )

        await manager.send_status(doc_id, status, message_text)
