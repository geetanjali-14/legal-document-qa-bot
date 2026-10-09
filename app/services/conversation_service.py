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


import re


def generate_conversation_title(question: str) -> str:
    """
    Generates a concise, meaningful title from the user's first question/message,
    similar to ChatGPT naming conventions.
    """
    if not question:
        return "Legal Consultation"

    text = question.strip()
    # Strip quotes, markdown, trailing question marks and punctuation
    text = re.sub(r"^[\"\'`]+|[\"\'`\?\.\!\;:]+$", "", text).strip()
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    # Strip leading polite / filler prompts:
    prefix_patterns = [
        r"^(?:please\s+)?(?:can\s+you\s+|could\s+you\s+|would\s+you\s+)?(?:please\s+)?(?:kindly\s+)?(?:tell\s+me\s+|explain\s+|describe\s+|summarize\s+|detail\s+|clarify\s+)(?:to\s+me\s+)?(?:about\s+)?",
        r"^(?:i\s+want\s+to\s+know\s+|i\s+would\s+like\s+to\s+know\s+|let\s+me\s+know\s+)(?:about\s+)?",
        r"^(?:tell\s+me\s+about\s+|what\s+can\s+you\s+tell\s+me\s+about\s+)"
    ]
    for p in prefix_patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE).strip()

    # Strip conversational lead-ins like "what the ... clause covers" -> "... clause"
    if re.match(r"^what\s+(?:the\s+)?(?:[a-z0-9_-]+\s+){1,4}(?:clause|section|term|provision)", text, re.IGNORECASE):
        text = re.sub(r"^what\s+(?:the\s+)?", "", text, flags=re.IGNORECASE)

    # Pattern: "how is/are [the] [first/second] X calculated/computed/determined" -> "X Calculation"
    m_calc = re.match(
        r"^how\s+(?:is|are)\s+(?:the\s+)?(?:first\s+|second\s+|third\s+)?(.*?)\s+(?:is\s+)?(?:calculated|computed|determined)$",
        text,
        flags=re.IGNORECASE
    )
    if m_calc:
        core = m_calc.group(1).strip()
        core = re.sub(r"^(?:the|a|an)\s+", "", core, flags=re.IGNORECASE)
        return f"{core} Calculation".title()

    # Pattern: "what is/are the X for/under Y" -> "Y X" (e.g. "notice period for early termination" -> "Early Termination Notice Period")
    m_inversion = re.match(r"^(?:what\s+(?:is|are)\s+(?:the\s+)?)(.*?)\s+(?:for|under)\s+(.*?)$", text, flags=re.IGNORECASE)
    if m_inversion:
        part1 = m_inversion.group(1).strip()
        part2 = m_inversion.group(2).strip()
        part1 = re.sub(r"^(?:the|a|an)\s+", "", part1, flags=re.IGNORECASE)
        part2 = re.sub(r"^(?:the|a|an)\s+", "", part2, flags=re.IGNORECASE)
        if len(part2.split()) <= 4 and not re.search(r"\b(when|if|that|which|is|are|was|were)\b", part2, flags=re.IGNORECASE):
            return f"{part2} {part1}".title()

    # Pattern: "what is/are [the] X" / "how does [the] X work" / "is there [any] X" / "how much is [the] X"
    lead_in = (
        r"^(?:what\s+(?:is|are|were|was)\s+(?:the\s+|a\s+|an\s+)?|"
        r"what\s+does\s+(?:the\s+)?|"
        r"how\s+(?:does|do|can|is)\s+(?:the\s+)?|"
        r"how\s+much\s+(?:is|are)\s+(?:the\s+)?|"
        r"is\s+there\s+(?:any\s+)?|"
        r"does\s+the\s+contract\s+have\s+(?:any\s+)?|"
        r"who\s+is\s+responsible\s+for\s+(?:the\s+)?)"
    )
    text = re.sub(lead_in, "", text, flags=re.IGNORECASE).strip()

    # Remove trailing verb phrases like "work", "mean", "apply", "cover", "specified", "stated"
    text = re.sub(r"\s+(?:work|mean|apply|operate|say|state|cover|covers|look\s+like)$", "", text, flags=re.IGNORECASE).strip()

    # Remove common leading articles
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE).strip()

    # Split into words and limit length
    words = text.split()
    if len(words) > 6:
        words = words[:6]

    # Strip trailing conjunctions/prepositions at boundary
    while words and words[-1].lower() in ("of", "for", "in", "to", "and", "or", "with", "the", "a", "an", "under"):
        words.pop()

    text = " ".join(words).strip()
    if not text:
        return "Legal Consultation"

    title = text.title()
    title = re.sub(r"\bNda\b", "NDA", title)
    title = re.sub(r"\bIp\b", "IP", title)
    title = re.sub(r"\bSla\b", "SLA", title)
    title = re.sub(r"\bLlc\b", "LLC", title)

    return title


class ConversationService:
    def __init__(self, repository: ConversationRepository):
        self.repository = repository

    def create_conversation(
        self,
        document_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> ConversationResponse:
        docs = list(document_ids or [])
        if document_id and document_id not in docs:
            docs.append(document_id)

        conv = self.repository.create_conversation(
            title=title,
            document_ids=docs,
            session_id=session_id
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

    def list_conversations(
        self,
        limit: int = 50,
        offset: int = 0,
        include_empty: bool = True,
        session_id: Optional[str] = None
    ) -> List[ConversationResponse]:
        items = self.repository.list_conversations(
            limit=limit,
            offset=offset,
            include_empty=include_empty,
            session_id=session_id
        )
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

        # Auto-generate meaningful title on the first user message if current title is generic or default
        if role == "user":
            conv = self.repository.get_conversation(conversation_id)
            if conv:
                is_first_user_msg = not any(m.role == "user" for m in conv.messages)
                current_title = (conv.title or "").strip()
                is_generic = (
                    not current_title
                    or current_title in ("New Chat", "Conversation", "Question", "General Consultation", "New Legal Consultation", "Chat")
                    or current_title.startswith("Consultation for ")
                    or current_title.startswith("New Chat")
                )
                if is_first_user_msg and is_generic:
                    generated_title = generate_conversation_title(content)
                    if generated_title:
                        self.repository.update_conversation(conversation_id, title=generated_title)

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

    def delete_conversation(self, conversation_id: str, document_id: Optional[str] = None, session_id: Optional[str] = None) -> bool:
        return self.repository.delete_conversation(conversation_id, document_id=document_id, session_id=session_id)

    def delete_all_conversations(self, document_id: Optional[str] = None, session_id: Optional[str] = None) -> int:
        return self.repository.delete_all_conversations(document_id=document_id, session_id=session_id)

    def ensure_conversation_exists(
        self,
        conversation_id: Optional[str],
        document_id: Optional[str] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None
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
            title=title or (f"Consultation for {document_id}" if document_id else "General Consultation"),
            session_id=session_id
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
