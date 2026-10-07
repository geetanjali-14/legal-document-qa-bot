from typing import List, Optional
from pydantic import BaseModel, Field
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

