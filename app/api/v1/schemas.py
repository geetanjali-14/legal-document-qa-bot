from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class V1ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Optional extra error details")


class V1ErrorResponse(BaseModel):
    error: V1ErrorDetail


class V1HealthResponse(BaseModel):
    status: str = Field(..., description="Service status, e.g. ok")
    app_name: str
    environment: str
    rag_provider: str
    llm_provider: str


class V1DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    page_count: int
    chunk_count: int
    content_hash: Optional[str] = None
    created_at: str


class V1DocumentDetailResponse(BaseModel):
    document_id: str
    filename: str
    original_filename: str
    file_size_bytes: int
    page_count: int
    chunk_count: int
    content_hash: Optional[str] = None
    status: str
    created_at: str


class V1DocumentListResponse(BaseModel):
    documents: List[V1DocumentDetailResponse]
    total: int


class V1DocumentDeleteResponse(BaseModel):
    success: bool
    document_id: str
    message: str


class V1ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Question text to query against the document")
    document_id: Optional[str] = Field(default=None, description="Document ID to query")
    conversation_id: Optional[str] = Field(default=None, description="Existing conversation session ID")
    top_k: Optional[int] = Field(default=None, ge=1, le=10, description="Top K evidence chunks to retrieve")


class V1SourceItem(BaseModel):
    document_id: str
    chunk_id: Optional[str] = None
    page_number: int
    section: Optional[str] = "General"
    section_title: Optional[str] = None
    clause_number: Optional[str] = None
    text_snippet: Optional[str] = None
    relevance_score: Optional[float] = None


class V1ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    document_id: Optional[str] = None
    sources: List[V1SourceItem] = []
    intent: Optional[str] = None
    confidence: Optional[str] = None
    model: Optional[str] = None
    disclaimer: Optional[str] = None


class V1ConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    document_id: Optional[str] = None
    document_ids: Optional[List[str]] = None


class V1ConversationResponse(BaseModel):
    id: str
    title: str
    status: str
    document_ids: List[str] = []
    message_count: int = 0
    created_at: str
    updated_at: str


class V1ConversationListResponse(BaseModel):
    conversations: List[V1ConversationResponse]
    total: int


class V1MessageItem(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    sources: List[V1SourceItem] = []


class V1ConversationDetailResponse(BaseModel):
    id: str
    title: str
    status: str
    document_ids: List[str] = []
    messages: List[V1MessageItem] = []
    created_at: str
    updated_at: str

