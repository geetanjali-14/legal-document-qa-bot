from typing import List, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from app.persistence.models import (
    ConversationModel,
    MessageModel,
    DocumentProfileModel,
    DocumentRecordModel,
    utc_now
)
from app.core.logging import logger


class ConversationRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def create_conversation(
        self,
        conversation_id: Optional[str] = None,
        title: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        session_id: Optional[str] = None
    ) -> ConversationModel:
        with self.session_factory() as session:
            doc_ids = document_ids or []
            conv = ConversationModel(
                title=title or "New Legal Consultation",
                document_ids=doc_ids,
                session_id=session_id
            )
            if conversation_id:
                conv.conversation_id = conversation_id
            session.add(conv)
            session.commit()
            session.refresh(conv)
            logger.info(f"Created conversation {conv.conversation_id} with docs {doc_ids} [session={session_id}]")
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

    def list_conversations(
        self,
        limit: int = 50,
        offset: int = 0,
        include_empty: bool = True,
        session_id: Optional[str] = None
    ) -> List[Tuple[ConversationModel, int]]:
        """
        Returns list of (ConversationModel, message_count) ordered by updated_at descending.
        When include_empty is False, only returns conversations containing at least one meaningful user message.
        When session_id is provided, filters strictly by session_id.
        """
        with self.session_factory() as session:
            # Query message count and user message count
            subq = (
                session.query(
                    MessageModel.conversation_id,
                    func.count(MessageModel.message_id).label("msg_count"),
                    func.sum(
                        case((MessageModel.role == "user", 1), else_=0)
                    ).label("user_msg_count")
                )
                .group_by(MessageModel.conversation_id)
                .subquery()
            )

            query = (
                session.query(ConversationModel, func.coalesce(subq.c.msg_count, 0))
                .outerjoin(subq, ConversationModel.conversation_id == subq.c.conversation_id)
            )

            if session_id is not None:
                query = query.filter(ConversationModel.session_id == session_id)

            if not include_empty:
                query = query.filter(func.coalesce(subq.c.user_msg_count, 0) > 0)

            query = (
                query
                .order_by(ConversationModel.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )

            results = []
            for conv, count in query.all():
                session.expunge(conv)
                results.append((conv, count))
            return results

    def cleanup_empty_conversations(self) -> int:
        """
        Defensive cleanup: removes any persisted conversations that have zero user messages
        or zero messages altogether.
        """
        with self.session_factory() as session:
            subq = (
                session.query(
                    MessageModel.conversation_id,
                    func.sum(
                        case((MessageModel.role == "user", 1), else_=0)
                    ).label("user_count")
                )
                .group_by(MessageModel.conversation_id)
                .subquery()
            )

            empty_convs = (
                session.query(ConversationModel)
                .outerjoin(subq, ConversationModel.conversation_id == subq.c.conversation_id)
                .filter(
                    (subq.c.user_count == None) | (subq.c.user_count == 0)
                )
                .all()
            )

            deleted_count = len(empty_convs)
            for conv in empty_convs:
                session.delete(conv)
            session.commit()
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} empty conversation(s) lacking user messages.")
            return deleted_count

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

    def delete_conversation(self, conversation_id: str, document_id: Optional[str] = None, session_id: Optional[str] = None) -> bool:
        with self.session_factory() as session:
            query = session.query(ConversationModel).filter(
                ConversationModel.conversation_id == conversation_id
            )
            if session_id is not None:
                query = query.filter(ConversationModel.session_id == session_id)
            conv = query.first()
            if not conv:
                return False
            if document_id and document_id not in (conv.document_ids or []):
                return False
            session.delete(conv)
            session.commit()
            logger.info(f"Deleted conversation {conversation_id} (session={session_id})")
            return True

    def delete_all_conversations(self, document_id: Optional[str] = None, session_id: Optional[str] = None) -> int:
        """Deletes conversations and their messages. Scoped by document_id and session_id if provided."""
        with self.session_factory() as session:
            query = session.query(ConversationModel)
            if session_id is not None:
                query = query.filter(ConversationModel.session_id == session_id)
            convs = query.all()
            to_delete = []
            for conv in convs:
                if document_id:
                    if document_id in (conv.document_ids or []):
                        to_delete.append(conv)
                else:
                    to_delete.append(conv)

            count = len(to_delete)
            for conv in to_delete:
                session.delete(conv)
            session.commit()
            logger.info(f"Deleted {count} conversation(s) (document_id filter={document_id}, session={session_id})")
            return count

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

    def save_document_record(self, meta_dict: dict) -> DocumentRecordModel:
        """Create or update DocumentRecordModel in database."""
        from app.persistence.models import DocumentRecordModel
        doc_id = meta_dict["document_id"]
        with self.session_factory() as session:
            existing = session.query(DocumentRecordModel).filter(
                DocumentRecordModel.document_id == doc_id
            ).first()
            if existing:
                for k, v in meta_dict.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
                session.commit()
                session.refresh(existing)
                session.expunge(existing)
                return existing
            else:
                doc = DocumentRecordModel(
                    document_id=doc_id,
                    filename=meta_dict.get("filename", ""),
                    original_filename=meta_dict.get("original_filename", ""),
                    file_size_bytes=meta_dict.get("file_size_bytes", 0),
                    page_count=meta_dict.get("page_count", 0),
                    chunk_count=meta_dict.get("chunk_count", 0),
                    mime_type=meta_dict.get("mime_type"),
                    content_hash=meta_dict.get("content_hash", ""),
                    document_type=meta_dict.get("document_type"),
                    processing_status=meta_dict.get("processing_status", "completed"),
                    ocr_status=meta_dict.get("ocr_status", "not_required"),
                    parser_version=meta_dict.get("parser_version", "v2.0"),
                    embedding_version=meta_dict.get("embedding_version", "v2.0"),
                    embedding_provider=meta_dict.get("embedding_provider"),
                    embedding_model=meta_dict.get("embedding_model"),
                    embedding_dimension=meta_dict.get("embedding_dimension"),
                    status=meta_dict.get("status", "processed"),
                    error_message=meta_dict.get("error_message"),
                    doc_type=meta_dict.get("doc_type", "pdf"),
                    upload_timestamp=meta_dict.get("upload_timestamp"),
                )
                session.add(doc)
                session.commit()
                session.refresh(doc)
                session.expunge(doc)
                return doc

    def list_document_records(self) -> List[DocumentRecordModel]:
        """List all DocumentRecordModel entities."""
        from app.persistence.models import DocumentRecordModel
        with self.session_factory() as session:
            docs = session.query(DocumentRecordModel).order_by(DocumentRecordModel.created_at.desc()).all()
            session.expunge_all()
            return docs

    def get_document_record(self, document_id: str) -> Optional[DocumentRecordModel]:
        from app.persistence.models import DocumentRecordModel
        with self.session_factory() as session:
            doc = session.query(DocumentRecordModel).filter(
                DocumentRecordModel.document_id == document_id
            ).first()
            if doc:
                session.expunge(doc)
            return doc

    def find_document_record_by_hash(self, content_hash: str) -> Optional[DocumentRecordModel]:
        from app.persistence.models import DocumentRecordModel
        with self.session_factory() as session:
            doc = session.query(DocumentRecordModel).filter(
                DocumentRecordModel.content_hash == content_hash
            ).first()
            if doc:
                session.expunge(doc)
            return doc

    def delete_document_record(self, document_id: str) -> bool:
        from app.persistence.models import DocumentRecordModel
        with self.session_factory() as session:
            doc = session.query(DocumentRecordModel).filter(
                DocumentRecordModel.document_id == document_id
            ).first()
            if not doc:
                return False
            session.delete(doc)
            session.commit()
            return True

    def save_document_chunks(
        self,
        document_id: str,
        chunks: list,
        embeddings: list
    ) -> int:
        """Persist document chunks and embeddings into document_chunks table."""
        from app.persistence.models import DocumentChunkModel
        with self.session_factory() as session:
            # Delete existing chunks for document_id first
            session.query(DocumentChunkModel).filter(
                DocumentChunkModel.document_id == document_id
            ).delete()

            chunk_records = []
            for idx, (chunk, vec) in enumerate(zip(chunks, embeddings)):
                emb_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                c_model = DocumentChunkModel(
                    document_id=document_id,
                    chunk_id=chunk.chunk_id if hasattr(chunk, "chunk_id") else chunk.get("chunk_id", f"chk_{idx}"),
                    chunk_index=idx,
                    page_number=getattr(chunk, "page_number", None) or (chunk.get("page_number", 1) if isinstance(chunk, dict) else 1),
                    section=getattr(chunk, "section", None) or (chunk.get("section") if isinstance(chunk, dict) else None),
                    section_number=getattr(chunk, "section_number", None) or (chunk.get("section_number") if isinstance(chunk, dict) else None),
                    section_title=getattr(chunk, "section_title", None) or (chunk.get("section_title") if isinstance(chunk, dict) else None),
                    clause_number=getattr(chunk, "clause_number", None) or (chunk.get("clause_number") if isinstance(chunk, dict) else None),
                    paragraph_number=getattr(chunk, "paragraph_number", None) or (chunk.get("paragraph_number") if isinstance(chunk, dict) else None),
                    parent_chunk_id=getattr(chunk, "parent_chunk_id", None) or (chunk.get("parent_chunk_id") if isinstance(chunk, dict) else None),
                    text=chunk.text if hasattr(chunk, "text") else chunk.get("text", ""),
                    token_count=getattr(chunk, "token_count", None) or (chunk.get("token_count") if isinstance(chunk, dict) else None),
                    content_hash=getattr(chunk, "content_hash", None) or (chunk.get("content_hash") if isinstance(chunk, dict) else None),
                    breadcrumbs=getattr(chunk, "breadcrumbs", None) or (chunk.get("breadcrumbs", []) if isinstance(chunk, dict) else []),
                    embedding=emb_list
                )
                chunk_records.append(c_model)

            session.add_all(chunk_records)
            session.commit()
            return len(chunk_records)

    def get_document_chunks(self, document_id: str) -> list:
        """Fetch all chunks with embeddings for document_id ordered by chunk_index."""
        from app.persistence.models import DocumentChunkModel
        with self.session_factory() as session:
            rows = session.query(DocumentChunkModel).filter(
                DocumentChunkModel.document_id == document_id
            ).order_by(DocumentChunkModel.chunk_index).all()
            session.expunge_all()
            return rows

    def delete_document_chunks(self, document_id: str) -> int:
        """Delete all chunks for document_id."""
        from app.persistence.models import DocumentChunkModel
        with self.session_factory() as session:
            count = session.query(DocumentChunkModel).filter(
                DocumentChunkModel.document_id == document_id
            ).delete()
            session.commit()
            return count
