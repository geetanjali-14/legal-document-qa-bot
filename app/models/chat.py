from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from app.core.telemetry import ChatTelemetry


class Citation(BaseModel):
    document_id: str
    document_name: str
    page_number: int
    section: Optional[str] = "General"
    chunk_id: str
    snippet: str
    relevance_score: Optional[float] = None


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    document_id: str
    question: str = Field(..., min_length=2)
    history: Optional[List[Message]] = Field(default_factory=list)
    top_k: Optional[int] = Field(default=None, ge=1)
    conversation_id: Optional[str] = None

    @field_validator("question")
    @classmethod
    def validate_non_whitespace(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Question cannot be empty or contain only whitespace.")
        return v


class ChatResponse(BaseModel):
    answer: str
    sources: List[Citation] = Field(default_factory=list)
    confidence: str = "supported"  # "supported", "partially_supported", "insufficient_context", "low_confidence"
    disclaimer: str = (
        "This tool provides information extracted from uploaded legal documents "
        "and is not a substitute for formal legal advice from a qualified attorney."
    )
    request_id: Optional[str] = None
    telemetry: Optional[ChatTelemetry] = None
    conversation_id: Optional[str] = None
    audit_trace: Optional[dict] = None

