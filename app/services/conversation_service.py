from typing import List, Optional
from app.models.conversation import (
    ConversationResponse,
    ConversationDetailResponse,
    MessageResponse
)
from app.models.chat import Citation, Message
from app.core.telemetry import ChatTelemetry, estimate_tokens
from app.core.config import settings
from app.persistence.repository import ConversationRepository
from app.core.logging import logger


class ConversationService:
    def __init__(self, repository: ConversationRepository):
        self.repository = repository

    def create_conversation(
        self,
        document_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        title: Optional[str] = None
    ) -> ConversationResponse:
        docs = list(document_ids or [])
        if document_id and document_id not in docs:
            docs.append(document_id)

        conv = self.repository.create_conversation(
            title=title,
            document_ids=docs
        )
        return self._to_conversation_response(conv, message_count=0)

    def get_conversation(self, conversation_id: str) -> Optional[ConversationDetailResponse]:
        conv = self.repository.get_conversation(conversation_id)
        if not conv:
            return None
        messages = [self._to_message_response(m) for m in conv.messages]
        return ConversationDetailResponse(
            conversation_id=conv.conversation_id,
            title=conv.title,
            document_ids=conv.document_ids or [],
            status=conv.status,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=len(messages),
            messages=messages
        )

    def list_conversations(self, limit: int = 50, offset: int = 0, include_empty: bool = True) -> List[ConversationResponse]:
        items = self.repository.list_conversations(limit=limit, offset=offset, include_empty=include_empty)
        return [self._to_conversation_response(conv, count) for conv, count in items]

    def cleanup_empty_conversations(self) -> int:
        return self.repository.cleanup_empty_conversations()

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        evidence_state: Optional[str] = None,
        sources: Optional[List[Citation]] = None,
        telemetry: Optional[ChatTelemetry] = None
    ) -> MessageResponse:
        sources_dicts = [s.model_dump() for s in sources] if sources else []
        telemetry_dict = telemetry.model_dump() if telemetry else None

        msg = self.repository.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            intent=intent,
            evidence_state=evidence_state,
            sources=sources_dicts,
            telemetry=telemetry_dict
        )
        return self._to_message_response(msg)

    def update_conversation(
        self,
        conversation_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        document_ids: Optional[List[str]] = None
    ) -> Optional[ConversationResponse]:
        conv = self.repository.update_conversation(
            conversation_id=conversation_id,
            title=title,
            status=status,
            document_ids=document_ids
        )
        if not conv:
            return None
        messages = self.repository.get_messages(conversation_id)
        return self._to_conversation_response(conv, message_count=len(messages))

    def delete_conversation(self, conversation_id: str, document_id: str) -> bool:
        return self.repository.delete_conversation(conversation_id, document_id)

    def delete_all_conversations(self, document_id: Optional[str] = None) -> int:
        return self.repository.delete_all_conversations(document_id=document_id)

    def ensure_conversation_exists(
        self,
        conversation_id: Optional[str],
        document_id: Optional[str] = None,
        title: Optional[str] = None
    ) -> ConversationResponse:
        """
        Validates provided conversation_id or automatically creates a new conversation
        bound to document_id (if provided) if conversation_id is None.
        If existing conversation does not contain document_id, appends it.
        """
        if conversation_id:
            conv = self.repository.get_conversation(conversation_id)
            if not conv:
                raise ValueError(f"Conversation with ID '{conversation_id}' was not found.")
            # Ensure document_id is registered in document_ids if provided
            if document_id:
                doc_ids = list(conv.document_ids or [])
                if document_id not in doc_ids:
                    doc_ids.append(document_id)
                    self.repository.update_conversation(conversation_id, document_ids=doc_ids)
                    conv.document_ids = doc_ids
            return self._to_conversation_response(conv, message_count=len(conv.messages))

        # Create new conversation automatically
        return self.create_conversation(
            document_id=document_id,
            title=title or (f"Consultation for {document_id}" if document_id else "General Consultation")
        )

    def get_bounded_history(
        self,
        conversation_id: str,
        max_turns: Optional[int] = None,
        max_tokens: Optional[int] = None
    ) -> List[Message]:
        """
        Retrieves recent conversation history bounded by max turns and max tokens.
        Strips verbose citations or system metadata to conserve prompt token budget.
        Trims oldest turns first when exceeding token budget.
        """
        limit_turns = max_turns if max_turns is not None else settings.MAX_HISTORY_TURNS
        limit_tokens = max_tokens if max_tokens is not None else settings.MAX_HISTORY_TOKENS

        raw_messages = self.repository.get_messages(conversation_id)
        if not raw_messages:
            return []

        # Each turn is typically a user + assistant pair, so max_turns * 2 messages
        max_message_count = max(1, limit_turns * 2)
        recent_msgs = raw_messages[-max_message_count:]

        # Map to lightweight Message models with clean text content
        history: List[Message] = []
        for m in recent_msgs:
            if m.role in ("user", "assistant"):
                clean_content = m.content.strip()
                history.append(Message(role=m.role, content=clean_content))

        # Enforce token budget: trim oldest messages until within limit_tokens
        if limit_tokens and limit_tokens > 0:
            while history:
                total_text = "\n".join(f"{msg.role}: {msg.content}" for msg in history)
                if estimate_tokens(total_text) <= limit_tokens:
                    break
                # Pop oldest message
                history.pop(0)

        return history

    @staticmethod
    def _to_conversation_response(conv, message_count: int = 0) -> ConversationResponse:
        return ConversationResponse(
            conversation_id=conv.conversation_id,
            title=conv.title,
            document_ids=conv.document_ids or [],
            status=conv.status,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=message_count
        )

    @staticmethod
    def _to_message_response(msg) -> MessageResponse:
        citations = [Citation(**c) for c in (msg.sources or [])]
        telemetry = ChatTelemetry(**msg.telemetry) if msg.telemetry else None
        return MessageResponse(
            message_id=msg.message_id,
            conversation_id=msg.conversation_id,
            role=msg.role,
            content=msg.content,
            sequence=msg.sequence,
            intent=msg.intent,
            evidence_state=msg.evidence_state,
            sources=citations,
            telemetry=telemetry,
            created_at=msg.created_at
        )
