# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()
class Settings(BaseSettings):
    PROJECT_NAME: str
    ENVIRONMENT: str

    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str

    REDIS_URL: str

    CHROMA_PATH: str

    JWT_SECRET_KEY: str
    OPENAI_API_KEY: str

    # Comma-separated list of allowed CORS origins.
    # Override in Render env vars when your Vercel URL is known.
    ALLOWED_ORIGINS: str = "http://localhost:5173,https://localhost:5173"
    
    model_config = SettingsConfigDict(
        env_file=".env",          # Load variables from .env automatically
        env_file_encoding="utf-8"
    )

# Instantiate settings
settings = Settings()

print(f"[CONFIG] Loaded settings for {settings.PROJECT_NAME} [{settings.ENVIRONMENT}]")
