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
    section_number: Optional[str] = None
    section_title: Optional[str] = None
    clause_number: Optional[str] = None
    paragraph_number: Optional[int] = None
    parent_chunk_id: Optional[str] = None
    text: str
    token_count: Optional[int] = None
    content_hash: Optional[str] = None
    breadcrumbs: List[str] = Field(default_factory=list)


class DocumentMetadata(BaseModel):
    document_id: str
    filename: str
    original_filename: str
    file_size_bytes: int
    page_count: int
    chunk_count: int
    mime_type: Optional[str] = None
    content_hash: Optional[str] = None
    document_type: Optional[str] = None  # e.g., "contract", "lease", "nda"
    processing_status: Optional[str] = "completed"
    ocr_status: Optional[str] = "not_required"
    parser_version: Optional[str] = "v2.0"
    embedding_version: Optional[str] = "v2.0"
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    status: str = "processed"  # uploaded, processing, processed, error
    error_message: Optional[str] = None
    doc_type: Optional[str] = None  # "pdf" or "image"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    upload_timestamp: Optional[str] = None

