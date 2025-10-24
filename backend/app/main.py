# app/main.py

from fastapi import FastAPI,Depends
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from .routers.admin import router as admin_router
from fastapi.openapi.utils import get_openapi
from app.utils.auth import require_admin

#Local imports
from .config import settings
from .core.database import init_db, close_db
from .core.redis_client import init_redis, close_redis
from .core.chroma_client import init_chroma, close_chroma
from  .utils.auth import require_user

#Import routers (they’ll be added later)
from .routers import auth, chat, docs, monitor


# -------------------------------------------------------------
# ✅ Initialize FastAPI App
# -------------------------------------------------------------
app = FastAPI(
    title="KnowServe API",
    version="1.0.0",
    description="Multi-agent organizational knowledge assistant backend.",
)


# -------------------------------------------------------------
# 🌐 CORS Configuration
# -------------------------------------------------------------
origins = [
    "http://localhost:5173",          # Vite frontend (local dev)
    "https://knowserve.vercel.app",   # Production frontend might change
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------
# 🚀 Startup / Shutdown Events
# -------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Initialize connections to external services on startup."""
    await asyncio.gather(
        init_db(),
        init_redis(),
        init_chroma(),
    )
    print("✅ KnowServe backend started successfully.")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanly close connections on shutdown."""
    await asyncio.gather(
        close_db(),
        close_redis(),
        close_chroma(),
    )
    print("🛑 KnowServe backend shut down cleanly.")


# -------------------------------------------------------------
# 🧠 Include Routers (to be added later)
# -------------------------------------------------------------
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"],dependencies=[Depends(require_user)])
app.include_router(docs.router, prefix="/documents", tags=["Documents"], dependencies=[Depends(require_user)])
app.include_router(admin_router, prefix="/admin", tags=["Admin"],dependencies=[Depends(require_admin)])
app.include_router(monitor.router, prefix="/monitor", tags=["Monitoring"],dependencies=[Depends(require_admin)])


# -------------------------------------------------------------
# 💓 Health Check Endpoint
# -------------------------------------------------------------
@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }

    # Apply security to all paths except /auth endpoints
    for path, methods in openapi_schema["paths"].items():
        if not path.startswith("/auth"):  # don't require token for /auth
            for method in methods.values():
                method.setdefault("security", [{"BearerAuth": []}])

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


