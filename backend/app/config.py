# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "KnowServe"
    ENVIRONMENT: str = "development"

settings = Settings()
print(f"⚙️ Loaded settings for {settings.PROJECT_NAME} [{settings.ENVIRONMENT}]")
print(f"⚙️ Loaded settings!")
