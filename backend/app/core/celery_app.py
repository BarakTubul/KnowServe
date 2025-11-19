from celery import Celery
from app.config import settings

celery_app = Celery(
    "knowserve",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# ✅ Autodiscover tasks from this package
celery_app.autodiscover_tasks(["app.tasks"])
