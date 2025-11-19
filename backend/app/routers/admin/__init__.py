# app/routers/admin/__init__.py
from fastapi import APIRouter
from app.routers.admin import docs

router = APIRouter(
    tags=["Admin"]
)

# Include all admin sub-routers
router.include_router(docs.router, prefix="/docs")

