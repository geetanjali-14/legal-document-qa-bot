from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class PageContent(BaseModel):
    page_number: int
    text: str
    char_count: int


class DocumentChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    page_number: int
    section: Optional[str] = "General"
    text: str
    token_count: Optional[int] = None
    breadcrumbs: List[str] = Field(default_factory=list)


class DocumentMetadata(BaseModel):
    document_id: str
    filename: str
    original_filename: str
    file_size_bytes: int
    page_count: int
    chunk_count: int
    content_hash: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    status: str = "processed"  # uploaded, processing, processed, error
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

