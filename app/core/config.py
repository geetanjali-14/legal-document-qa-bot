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
    CORS_ALLOWED_ORIGINS: str = "*"

    # Demo mode & Public safety
    DEMO_MODE: bool = False
    DEMO_DOCUMENTS_DIR: Path = Path("documents")
    SESSION_SECRET: str = "dev-insecure-secret-change-in-production"
    RATE_LIMIT_CHAT_PER_MINUTE: int = 15
    RATE_LIMIT_CONV_PER_MINUTE: int = 30

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

    # RAG Provider
    RAG_PROVIDER: Literal["local"] = "local"

    # LLM Provider
    LLM_PROVIDER: Literal["groq", "gemini", "openai", "mock"] = "groq"
    LLM_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_BASE_URL: str = ""
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 1024

    # Embedding Provider
    EMBEDDING_PROVIDER: Literal["gemini", "fastembed", "tfidf", "openai", "mock"] = "tfidf"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_BASE_URL: str = ""

    # Slack Integration
    SLACK_BOT_TOKEN: str = ""
    SLACK_APP_TOKEN: str = ""
    LEGAL_QA_API_BASE_URL: str = "http://localhost:8000/api/v1"


settings = Settings()

