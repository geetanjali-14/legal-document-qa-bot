import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    JSON,
    Index
)
from sqlalchemy.orm import relationship
from app.persistence.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationModel(Base):
    __tablename__ = "conversations"

    conversation_id = Column(String(36), primary_key=True, default=lambda: f"conv_{uuid.uuid4().hex[:16]}")
    title = Column(String(255), nullable=False, default="New Legal Consultation")
    document_ids = Column(JSON, nullable=False, default=list)  # Stored as JSON list of doc IDs: ["doc_123"]
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    messages = relationship(
        "MessageModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageModel.sequence"
    )


class MessageModel(Base):
    __tablename__ = "messages"

    message_id = Column(String(36), primary_key=True, default=lambda: f"msg_{uuid.uuid4().hex[:16]}")
    conversation_id = Column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)  # "user", "assistant", "system"
    content = Column(Text, nullable=False)
    sequence = Column(Integer, nullable=False, default=1)
    intent = Column(String(64), nullable=True)
    evidence_state = Column(String(64), nullable=True)
    sources = Column(JSON, nullable=True, default=list)  # Serialized list of Citation dicts
    telemetry = Column(JSON, nullable=True)  # Serialized ChatTelemetry dict
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation = relationship("ConversationModel", back_populates="messages")


class DocumentProfileModel(Base):
    __tablename__ = "document_profiles"

    document_id = Column(String(36), primary_key=True)
    content_hash = Column(String(64), nullable=False, index=True)
    document_type = Column(String(128), nullable=False)
    parties = Column(JSON, nullable=False, default=list)  # List of party names
    effective_date = Column(String(64), nullable=True)
    executive_summary = Column(Text, nullable=False)
    major_topics = Column(JSON, nullable=False, default=list)  # List of topics/sections
    source_pages = Column(JSON, nullable=False, default=list)
    source_sections = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class SlackConversationMappingModel(Base):
    __tablename__ = "slack_conversation_mappings"

    # Unique context key: "{team_id}:{channel_id}:{thread_ts_or_root}:{user_id}"
    context_key = Column(String(128), primary_key=True)
    team_id = Column(String(64), nullable=False, default="")
    channel_id = Column(String(64), nullable=False)
    thread_ts = Column(String(64), nullable=False, default="")
    user_id = Column(String(64), nullable=False)
    document_id = Column(String(64), nullable=True)
    conversation_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


Index("idx_messages_conv_seq", MessageModel.conversation_id, MessageModel.sequence)
Index("idx_conversations_updated", ConversationModel.updated_at.desc())
Index("idx_doc_profiles_hash", DocumentProfileModel.content_hash)
Index("idx_slack_mapping_user", SlackConversationMappingModel.user_id, SlackConversationMappingModel.channel_id)

