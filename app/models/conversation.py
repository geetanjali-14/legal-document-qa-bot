from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from app.core.telemetry import ChatTelemetry
from app.models.chat import Citation


RoleType = Literal["user", "assistant", "system"]


class ConversationCreate(BaseModel):
    document_id: Optional[str] = None
    document_ids: Optional[List[str]] = Field(default_factory=list)
    title: Optional[str] = None


class MessageCreate(BaseModel):
    role: RoleType
    content: str
    intent: Optional[str] = None
    evidence_state: Optional[str] = None
    sources: Optional[List[Citation]] = Field(default_factory=list)
    telemetry: Optional[ChatTelemetry] = None


class MessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    role: RoleType
    content: str
    sequence: int
    intent: Optional[str] = None
    evidence_state: Optional[str] = None
    sources: List[Citation] = Field(default_factory=list)
    telemetry: Optional[ChatTelemetry] = None
    created_at: datetime


class ConversationResponse(BaseModel):
    conversation_id: str
    title: str
    document_ids: List[str] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationDetailResponse(ConversationResponse):
    messages: List[MessageResponse] = Field(default_factory=list)


class ConversationContextState(BaseModel):
    """
    Lightweight structured representation of multi-turn conversation state (Phase 1).
    Tracks active legal concepts, parties, sections, and events without external dependencies.
    """
    active_document: Optional[str] = None
    active_topic: Optional[str] = None
    active_clause: Optional[str] = None
    active_parties: List[str] = Field(default_factory=list)
    active_entities: List[str] = Field(default_factory=list)
    active_definitions: List[str] = Field(default_factory=list)
    active_events: List[str] = Field(default_factory=list)
    last_resolved_query: Optional[str] = None
    conversation_summary: Optional[str] = None

