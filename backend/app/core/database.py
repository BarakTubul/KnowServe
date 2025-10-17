# app/core/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

# ---------------------------
# Database configuration
# ---------------------------

# Build PostgreSQL connection string
DATABASE_URL = (
    f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}"
    f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
)

# Create SQLAlchemy engine (connection pool)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Session factory for database operations
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base for ORM models
Base = declarative_base()


# ---------------------------
# Async lifecycle management
# ---------------------------

async def init_db():
    """
    Initialize the database connection and create all tables.
    Called once at application startup.
    """
    print("🔄 Connecting to PostgreSQL...")

    try:
        # Lazy import ensures all model modules are loaded first
        from app.models import Base  # imports __init__.py, which imports all models

        # Create all tables (only if they don't exist)
        Base.metadata.create_all(bind=engine)
        print("✅ Database connected and tables ready.")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise e


async def close_db():
    """Dispose all SQLAlchemy connections on shutdown."""
    engine.dispose()
    print("🛑 Database engine disposed.")


def get_db():
    """Provide a new database session for each request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
