from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from app.models.chat import Citation
from app.core.telemetry import ChatTelemetry


class IntentType(str, Enum):
    METADATA = "METADATA"
    DOCUMENT_OVERVIEW = "DOCUMENT_OVERVIEW"
    STRUCTURE_NAVIGATION = "STRUCTURE_NAVIGATION"
    EVIDENCE_SEARCH = "EVIDENCE_SEARCH"
    CROSS_SECTION_ANALYSIS = "CROSS_SECTION_ANALYSIS"
    MULTI_DOCUMENT_COMPARE = "MULTI_DOCUMENT_COMPARE"
    UNSUPPORTED = "UNSUPPORTED"
    WHOLE_DOCUMENT = "WHOLE_DOCUMENT"
    OBLIGATION = "OBLIGATION"
    RISK = "RISK"
    DEFINITION = "DEFINITION"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    CLAUSE_LOOKUP = "CLAUSE_LOOKUP"
    DIRECT_FACT = "DIRECT_FACT"
    UNANSWERABLE = "UNANSWERABLE"


class UncertaintyState(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_EVIDENCE = "insufficient_context"
    NOT_FOUND = "not_found"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    CLARIFICATION_REQUIRED = "clarification_required"


class IntentRoutingResult(BaseModel):
    primary_intent: IntentType
    intents: List[IntentType]
    confidence: float = 1.0
    is_multi_intent: bool = False
    sub_intents: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning: Optional[str] = None


class MetadataResult(BaseModel):
    document_id: str
    original_filename: str
    filename: str
    file_size_bytes: int
    page_count: int
    chunk_count: int
    content_hash: Optional[str] = None
    status: str = "processed"
    created_at: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None


class DocumentProfileResult(BaseModel):
    document_id: str
    content_hash: str
    document_type: str
    parties: List[str] = Field(default_factory=list)
    effective_date: Optional[str] = None
    executive_summary: str
    major_topics: List[str] = Field(default_factory=list)
    source_pages: List[int] = Field(default_factory=list)
    source_sections: List[str] = Field(default_factory=list)
    generated_at: str


class EvidenceItem(BaseModel):
    document_id: str
    chunk_id: str
    page_number: int
    section: Optional[str] = "General"
    score: float
    text: str
    document_name: Optional[str] = None


class EvidenceResult(BaseModel):
    document_ids: List[str]
    query: str
    items: List[EvidenceItem] = Field(default_factory=list)
    evidence_state: UncertaintyState = UncertaintyState.SUPPORTED
    latency_ms: float = 0.0


class ToolExecutionRecord(BaseModel):
    tool_name: str
    tool_input: Dict[str, Any]
    tool_output_summary: str
    evidence_state: Optional[str] = None
    latency_ms: float = 0.0
    tokens_used: int = 0


class AgentAuditTrace(BaseModel):
    request_id: str
    query: str
    iteration_count: int = 1
    selected_intent: str
    selected_tools: List[str] = Field(default_factory=list)
    tool_executions: List[ToolExecutionRecord] = Field(default_factory=list)
    final_evidence_state: str
    context_rewritten_query: Optional[str] = None
    answer_derivation_type: str = "deterministic"  # "deterministic_metadata", "grounded_synthesis", "refusal", "clarification"
