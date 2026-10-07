from typing import List, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.persistence.models import ConversationModel, MessageModel, DocumentProfileModel, utc_now
from app.core.logging import logger


class ConversationRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def create_conversation(
        self,
        conversation_id: Optional[str] = None,
        title: Optional[str] = None,
        document_ids: Optional[List[str]] = None
    ) -> ConversationModel:
        with self.session_factory() as session:
            doc_ids = document_ids or []
            conv = ConversationModel(
                title=title or "New Legal Consultation",
                document_ids=doc_ids
            )
            if conversation_id:
                conv.conversation_id = conversation_id
            session.add(conv)
            session.commit()
            session.refresh(conv)
            logger.info(f"Created conversation {conv.conversation_id} with docs {doc_ids}")
            return conv

    def get_conversation(self, conversation_id: str) -> Optional[ConversationModel]:
        with self.session_factory() as session:
            conv = session.query(ConversationModel).filter(
                ConversationModel.conversation_id == conversation_id
            ).first()
            if conv:
                # Eagerly access messages within active session
                _ = conv.messages
                # Detach by expunging so it can be returned outside session
                session.expunge_all()
            return conv

    def list_conversations(self, limit: int = 50, offset: int = 0) -> List[Tuple[ConversationModel, int]]:
        """Returns list of (ConversationModel, message_count) ordered by updated_at descending."""
        with self.session_factory() as session:
            # Query conversations with message counts
            subq = (
                session.query(
                    MessageModel.conversation_id,
                    func.count(MessageModel.message_id).label("msg_count")
                )
                .group_by(MessageModel.conversation_id)
                .subquery()
            )

            query = (
                session.query(ConversationModel, func.coalesce(subq.c.msg_count, 0))
                .outerjoin(subq, ConversationModel.conversation_id == subq.c.conversation_id)
                .order_by(ConversationModel.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )

            results = []
            for conv, count in query.all():
                session.expunge(conv)
                results.append((conv, count))
            return results

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        evidence_state: Optional[str] = None,
        sources: Optional[List[dict]] = None,
        telemetry: Optional[dict] = None
    ) -> MessageModel:
        with self.session_factory() as session:
            conv = session.query(ConversationModel).filter(
                ConversationModel.conversation_id == conversation_id
            ).first()
            if not conv:
                raise ValueError(f"Conversation with ID '{conversation_id}' not found.")

            # Calculate next sequence number atomically within transaction
            max_seq = session.query(func.max(MessageModel.sequence)).filter(
                MessageModel.conversation_id == conversation_id
            ).scalar() or 0
            next_seq = max_seq + 1

            now = utc_now()
            msg = MessageModel(
                conversation_id=conversation_id,
                role=role,
                content=content,
                sequence=next_seq,
                intent=intent,
                evidence_state=evidence_state,
                sources=sources or [],
                telemetry=telemetry,
                created_at=now
            )
            session.add(msg)
            # Update parent conversation's updated_at
            conv.updated_at = now
            session.commit()
            session.refresh(msg)
            session.expunge(msg)
            return msg

    def get_messages(self, conversation_id: str) -> List[MessageModel]:
        with self.session_factory() as session:
            msgs = (
                session.query(MessageModel)
                .filter(MessageModel.conversation_id == conversation_id)
                .order_by(MessageModel.sequence.asc())
                .all()
            )
            session.expunge_all()
            return msgs

    def update_conversation(
        self,
        conversation_id: str,
        title: Optional[str] = None,
        status: Optional[str] = None,
        document_ids: Optional[List[str]] = None
    ) -> Optional[ConversationModel]:
        with self.session_factory() as session:
            conv = session.query(ConversationModel).filter(
                ConversationModel.conversation_id == conversation_id
            ).first()
            if not conv:
                return None
            if title is not None:
                conv.title = title
            if status is not None:
                conv.status = status
            if document_ids is not None:
                conv.document_ids = document_ids
            conv.updated_at = utc_now()
            session.commit()
            session.refresh(conv)
            session.expunge(conv)
            return conv

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.session_factory() as session:
            conv = session.query(ConversationModel).filter(
                ConversationModel.conversation_id == conversation_id
            ).first()
            if not conv:
                return False
            session.delete(conv)
            session.commit()
            logger.info(f"Deleted conversation {conversation_id}")
            return True

    def save_document_profile(
        self,
        document_id: str,
        content_hash: str,
        document_type: str,
        parties: List[str],
        executive_summary: str,
        major_topics: List[str],
        source_pages: List[int],
        source_sections: List[str],
        effective_date: Optional[str] = None
    ) -> DocumentProfileModel:
        with self.session_factory() as session:
            existing = session.query(DocumentProfileModel).filter(
                DocumentProfileModel.document_id == document_id
            ).first()
            if existing:
                existing.content_hash = content_hash
                existing.document_type = document_type
                existing.parties = parties
                existing.effective_date = effective_date
                existing.executive_summary = executive_summary
                existing.major_topics = major_topics
                existing.source_pages = source_pages
                existing.source_sections = source_sections
                existing.created_at = utc_now()
                session.commit()
                session.refresh(existing)
                session.expunge(existing)
                return existing
            else:
                profile = DocumentProfileModel(
                    document_id=document_id,
                    content_hash=content_hash,
                    document_type=document_type,
                    parties=parties,
                    effective_date=effective_date,
                    executive_summary=executive_summary,
                    major_topics=major_topics,
                    source_pages=source_pages,
                    source_sections=source_sections,
                    created_at=utc_now()
                )
                session.add(profile)
                session.commit()
                session.refresh(profile)
                session.expunge(profile)
                return profile

    def get_document_profile(self, document_id: str) -> Optional[DocumentProfileModel]:
        with self.session_factory() as session:
            profile = session.query(DocumentProfileModel).filter(
                DocumentProfileModel.document_id == document_id
            ).first()
            if profile:
                session.expunge(profile)
            return profile

    def delete_document_profile(self, document_id: str) -> bool:
        with self.session_factory() as session:
            profile = session.query(DocumentProfileModel).filter(
                DocumentProfileModel.document_id == document_id
            ).first()
            if not profile:
                return False
            session.delete(profile)
            session.commit()
            return True
