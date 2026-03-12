# app/main.py

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import os

from .routers.admin import router as admin_router
from fastapi.openapi.utils import get_openapi
from app.utils.auth import require_admin

# Local imports
from .config import settings
from .core.database import init_db, close_db
from .core.redis_client import init_redis, close_redis
from .utils.auth import require_user

# Import routers
from .routers import auth, chat, docs, monitor, ws

os.environ["CHROMA_TELEMETRY"] = "false"

# -------------------------------------------------------------
# ✅ Initialize FastAPI App
# -------------------------------------------------------------
app = FastAPI(
    title="KnowServe API",
    version="1.0.0",
    description="Multi-agent organizational knowledge assistant backend.",
)

# Ensure Static directories exist and mount them
os.makedirs("app/static/docs", exist_ok=True)


# -------------------------------------------------------------
# 🌐 CORS Configuration
# -------------------------------------------------------------
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",")]

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
    """Initialize connections & start event listener on app startup."""
    
    print("\n🚀 [SYSTEM] KnowServe backend initializing...")

    # 1. Warm up heavy ML models and indices (LlamaIndex + HuggingFace)
    # This shifts the ~10-20s load time to boot instead of the first user query.
    from app.core.vector_store import get_embed_model, get_llama_index
    get_embed_model()
    get_llama_index()

    if os.environ.get("TESTING") == "1":
        print("🧪 Testing mode detected: skipping DB and Redis bg thread initialization.")
        return

    from app.core.event_listener import listen_for_ingestion_events
    import asyncio

    # 1️⃣ Initialize external dependencies in parallel
    await asyncio.gather(
        init_db(),
        init_redis()
    )

    # 2️⃣ Launch the Redis pub/sub listener in the background
    asyncio.create_task(listen_for_ingestion_events())
    print("📡 Redis event listener started")

    print("✅ KnowServe backend started successfully.")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanly close connections on shutdown."""
    
    if os.environ.get("TESTING") == "1":
        return

    await asyncio.gather(
        close_db(),
        close_redis()
    )
    print("🛑 KnowServe backend shut down cleanly.")


# -------------------------------------------------------------
# 🧠 Include Routers
# -------------------------------------------------------------
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"], dependencies=[Depends(require_user)])
app.include_router(docs.router, prefix="/documents", tags=["Documents"], dependencies=[Depends(require_user)])
app.include_router(admin_router, prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])
app.include_router(monitor.router, prefix="/monitor", tags=["Monitoring"], dependencies=[Depends(require_admin)])
app.include_router(ws.router, prefix="/ws", tags=["WebSocket"])

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
