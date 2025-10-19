# app/services/docs_service.py
import json
import httpx
from app.core.redis_client import redis_client
from app.core.chroma_client import chroma_client
from app.config import settings
from app.models.document import Document
from app.core.database import SessionLocal
from sqlalchemy.orm import Session

class DocsService:

    @staticmethod
    def fetch_from_external(department: str | None = None):
        """Fetch docs from external API and store in DB + Chroma + Redis."""
        db: Session = SessionLocal()

        try:
            base_url = settings.EXTERNAL_DOCS_API
            url = f"{base_url}?department={department}" if department else base_url

            response = httpx.get(url, timeout=20)
            response.raise_for_status()
            docs_data = response.json()

            for doc in docs_data:
                title = doc.get("title")
                source_url = doc.get("url") or doc.get("source_url")
                dept_name = doc.get("department") or department

                # Save or update document
                existing = db.query(Document).filter_by(source_url=source_url).first()
                if existing:
                    existing.title = title
                    existing.department_id = DocsService.map_department_name_to_id(db, dept_name)
                else:
                    new_doc = Document(
                        title=title,
                        source_url=source_url,
                        department_id=DocsService.map_department_name_to_id(db, dept_name)
                    )
                    db.add(new_doc)
                db.commit()

            # Refresh cache
            redis_client.delete("docs:list")
            print(f"✅ Documents synced for department: {department or 'all'}")

        except Exception as e:
            print(f"❌ Fetch failed: {e}")
        finally:
            db.close()

    @staticmethod
    def list_allowed(department_id: int):
        """Return allowed documents for a department (with Redis cache)."""
        cache_key = f"docs:dept:{department_id}"

        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        db: Session = SessionLocal()
        try:
            docs = db.query(Document).filter_by(department_id=department_id).all()
            results = [
                {"id": d.id, "title": d.title, "source_url": d.source_url}
                for d in docs
            ]
            redis_client.setex(cache_key, 600, json.dumps(results))
            return results
        finally:
            db.close()

    @staticmethod
    def map_department_name_to_id(db: Session, name: str):
        """Stub for mapping department name → id (implement later)."""
        from app.models.department import Department
        dept = db.query(Department).filter_by(name=name).first()
        return dept.id if dept else None
