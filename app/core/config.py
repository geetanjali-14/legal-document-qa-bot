from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "Legal Document QA Assistant"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Ingestion & storage
    UPLOAD_DIR: Path = Path("data/uploads")
    VECTOR_STORE_DIR: Path = Path("data/vector_store")
    MAX_FILE_SIZE_MB: int = 25
    MAX_CHUNKS_PER_DOC: int = 5000

    # Chunking
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    MIN_CHUNK_SIZE: int = 50

    # Retrieval
    TOP_K: int = 4
    SIMILARITY_THRESHOLD: float = 0.1

    # LLM Provider
    LLM_PROVIDER: Literal["mock", "openai", "anthropic", "ollama", "custom_http"] = "mock"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_BASE_URL: str = ""
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 1024

    # Embedding Provider
    EMBEDDING_PROVIDER: Literal["mock", "tfidf", "openai", "ollama"] = "tfidf"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_BASE_URL: str = ""


settings = Settings()
