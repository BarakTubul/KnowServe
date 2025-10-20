# app/routers/admin/__init__.py
from fastapi import APIRouter, Depends
from app.utils.auth import require_admin
from app.routers.admin import docs

router = APIRouter(
    tags=["Admin"],
    dependencies=[Depends(require_admin)]
)

# Include all admin sub-routers
router.include_router(docs.router, prefix="/docs")

