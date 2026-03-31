from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"

    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "europe-west3"
    RAG_CORPUS_NAME: str = ""
    GEMINI_MODEL_NAME: str = "gemini-2.5-flash"
    GOOGLE_API_KEY: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    CORS_ORIGINS: str = "*"
    STATIC_DIR: str = ""

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
