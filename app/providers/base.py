from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """
    Provider-neutral chunk retrieval result.
    Normalizes retrieval outputs across local (Qdrant/BM25) and remote (xAI/etc.) providers.
    """
    document_id: str
    chunk_id: str
    text: str
    score: float = 0.0
    page_number: int = 1
    section: Optional[str] = "General"
    section_number: Optional[str] = None
    section_title: Optional[str] = None
    clause_number: Optional[str] = None
    paragraph_number: Optional[int] = None
    document_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """
    Provider-neutral LLM generation response.
    Normalizes text generation outputs, latency, and token accounting across all providers.
    """
    content: str
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    token_usage_type: str = "unknown"  # "actual", "estimated", "unknown"
    estimated_input_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_output_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_total_tokens: Optional[int] = Field(default=None, ge=0)
    estimation_method: Optional[str] = None
    latency_ms: float = Field(default=0.0, ge=0.0)
    provider: str = ""
    model: str = ""

    def __str__(self) -> str:
        return self.content

