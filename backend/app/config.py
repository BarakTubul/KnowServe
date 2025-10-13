# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str
    ENVIRONMENT: str

    model_config = SettingsConfigDict(
        env_file=".env",          # Load variables from .env automatically
        env_file_encoding="utf-8"
    )

# Instantiate settings
settings = Settings()

print(f"⚙️ Loaded settings for {settings.PROJECT_NAME} [{settings.ENVIRONMENT}]")
