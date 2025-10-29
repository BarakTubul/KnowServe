# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    DRIVE_FOLDER_ENGINEERING:str
    DRIVE_FOLDER_HR:str
    DRIVE_FOLDER_FINANCE:str
    DRIVE_FOLDER_MARKETING:str
    DRIVE_FOLDER_RND:str
    # CREDENTIALS_PATH:str
    
    model_config = SettingsConfigDict(
        env_file=".env",          # Load variables from .env automatically
        env_file_encoding="utf-8"
    )

# Instantiate settings
settings = Settings()

print(f"⚙️ Loaded settings for {settings.PROJECT_NAME} [{settings.ENVIRONMENT}]")
