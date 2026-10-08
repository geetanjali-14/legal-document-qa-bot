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
    DATABASE_PATH: Path = Path("data/legal_qa.db")
    DATABASE_URL: str = ""  # e.g. postgresql://user:pass@localhost:5432/legal_qa (empty falls back to sqlite)
    MAX_FILE_SIZE_MB: int = 25
    MAX_DOCUMENT_PAGES: int = 500
    MAX_CHUNKS_PER_DOC: int = 5000

    # Supported formats
    SUPPORTED_IMAGE_EXTENSIONS: tuple = (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif")
    SUPPORTED_DOCUMENT_EXTENSIONS: tuple = (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif")

    # Chunking
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    MIN_CHUNK_SIZE: int = 50

    # Retrieval & Context Limits
    TOP_K: int = 4
    MAX_TOP_K: int = 10
    SIMILARITY_THRESHOLD: float = 0.1
    RELEVANCE_CONFIDENCE_THRESHOLD: float = 0.35
    MIN_CONTENT_WORD_OVERLAP: float = 0.35
    MAX_CONTEXT_CHARS: int = 8000

    # Chat & Token Limits
    MAX_QUERY_CHARS: int = 2000
    MAX_PROMPT_TOKENS: int = 4096
    MAX_OUTPUT_TOKENS: int = 1024
    MAX_HISTORY_TURNS: int = 3
    MAX_HISTORY_TOKENS: int = 500

    # LLM Provider
    LLM_PROVIDER: Literal["mock", "openai", "anthropic", "ollama", "gemini", "grok", "mistral", "custom_http"] = "mock"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_BASE_URL: str = ""
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 1024

    # Embedding Provider
    EMBEDDING_PROVIDER: Literal["mock", "tfidf", "fastembed", "openai", "ollama"] = "tfidf"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_BASE_URL: str = ""

    # OCR Provider
    OCR_PROVIDER: Literal["local", "mistral", "gemini"] = "local"
    OCR_API_KEY: str = ""


settings = Settings()
