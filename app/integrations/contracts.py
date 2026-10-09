from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class PlatformAction(str, Enum):
    ANSWER = "answer"
    SELECT_DOCUMENT = "select_document"
    LIST_DOCUMENTS = "list_documents"
    CLEAR_CONTEXT = "clear_context"
    HELP = "help"
    UPLOAD_FILE = "upload_file"
    ERROR = "error"


class PlatformIncomingMessage(BaseModel):
    """
    Standardized payload ingested from any platform adapter
    (Slack, Telegram, WhatsApp, Widget, etc.).
    """
    platform: str = "slack"
    tenant_id: Optional[str] = None
    channel_id: str
    thread_id: Optional[str] = None
    user_id: str
    text: str = ""
    event_id: Optional[str] = None
    file_bytes: Optional[bytes] = None
    filename: Optional[str] = None


class PlatformOutgoingResponse(BaseModel):
    """
    Standardized response returned by the shared coordinator
    to be formatted by platform-specific formatters.
    """
    action: PlatformAction
    text: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    document_id: Optional[str] = None
    conversation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

