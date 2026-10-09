from typing import Optional
from sqlalchemy.orm import Session
from app.persistence.database import DatabaseManager
from app.persistence.models import SlackConversationMappingModel, utc_now
from app.core.logging import logger


class SlackMappingRepository:
    """
    Manages persistence of mappings between Slack contexts
    (workspace, channel, thread, user) and backend document/conversation IDs.
    Ensures strict user and conversation isolation in SQLite / PostgreSQL.
    """

    def __init__(self, session_factory=None):
        if session_factory is None:
            db_manager = DatabaseManager()
            self.session_factory = db_manager.session_factory
        else:
            self.session_factory = session_factory

    @staticmethod
    def build_context_key(
        team_id: Optional[str],
        channel_id: str,
        thread_ts: Optional[str],
        user_id: str
    ) -> str:
        """
        Builds a unique composite key combining team, channel, thread, and user.
        Including user_id ensures that different users in the same channel/thread
        do not silently overwrite or hijack each other's active document or conversation context.
        """
        safe_team = team_id or "default_team"
        safe_thread = thread_ts or "root"
        return f"{safe_team}:{channel_id}:{safe_thread}:{user_id}"

    def get_mapping(
        self,
        channel_id: str,
        user_id: str,
        team_id: Optional[str] = None,
        thread_ts: Optional[str] = None
    ) -> Optional[SlackConversationMappingModel]:
        """Fetch active mapping for specific thread/root context."""
        key = self.build_context_key(team_id, channel_id, thread_ts, user_id)
        with self.session_factory() as session:
            mapping = session.query(SlackConversationMappingModel).filter(
                SlackConversationMappingModel.context_key == key
            ).first()
            if mapping:
                session.expunge(mapping)
                logger.info(f"[SlackMapping] Found mapping for key={key}: doc={mapping.document_id}, conv={mapping.conversation_id}")
                return mapping

        # Candidate keys to evaluate in order of preference
        candidates = [key]
        if thread_ts:
            candidates.append(self.build_context_key(team_id, channel_id, None, user_id))

        if team_id:
            candidates.append(self.build_context_key(None, channel_id, thread_ts, user_id))
            if thread_ts:
                candidates.append(self.build_context_key(None, channel_id, None, user_id))
        else:
            candidates.append(self.build_context_key("default_team", channel_id, thread_ts, user_id))
            if thread_ts:
                candidates.append(self.build_context_key("default_team", channel_id, None, user_id))

        with self.session_factory() as session:
            # First pass: Look for an exact or fallback key that has an active document_id
            for c_key in candidates:
                mapping = session.query(SlackConversationMappingModel).filter(
                    SlackConversationMappingModel.context_key == c_key
                ).first()
                if mapping and mapping.document_id:
                    session.expunge(mapping)
                    logger.info(f"[SlackMapping] Found active document mapping for key={c_key}: doc={mapping.document_id}, conv={mapping.conversation_id}")
                    return mapping

            # Second pass: If no document-attached mapping, return the first matching session
            for c_key in candidates:
                mapping = session.query(SlackConversationMappingModel).filter(
                    SlackConversationMappingModel.context_key == c_key
                ).first()
                if mapping:
                    session.expunge(mapping)
                    logger.info(f"[SlackMapping] Found conversation-only mapping for key={c_key}: doc={mapping.document_id}, conv={mapping.conversation_id}")
                    return mapping

        logger.info(f"[SlackMapping] No mapping found for channel={channel_id}, user={user_id}, thread={thread_ts}")
        return None

    def save_mapping(
        self,
        channel_id: str,
        user_id: str,
        team_id: Optional[str] = None,
        thread_ts: Optional[str] = None,
        document_id: Optional[str] = None,
        conversation_id: Optional[str] = None
    ) -> SlackConversationMappingModel:
        """Save or update mapping for given context."""
        key = self.build_context_key(team_id, channel_id, thread_ts, user_id)
        with self.session_factory() as session:
            mapping = session.query(SlackConversationMappingModel).filter(
                SlackConversationMappingModel.context_key == key
            ).first()

            if not mapping:
                mapping = SlackConversationMappingModel(
                    context_key=key,
                    team_id=team_id or "default_team",
                    channel_id=channel_id,
                    thread_ts=thread_ts or "root",
                    user_id=user_id,
                    document_id=document_id,
                    conversation_id=conversation_id
                )
                session.add(mapping)
            else:
                if document_id is not None:
                    mapping.document_id = document_id
                if conversation_id is not None:
                    mapping.conversation_id = conversation_id
                mapping.updated_at = utc_now()

            session.commit()
            session.refresh(mapping)
            session.expunge(mapping)
            logger.info(
                f"[SlackMapping] Saved mapping {key} -> doc={mapping.document_id}, conv={mapping.conversation_id}"
            )
            return mapping

    def clear_mapping(
        self,
        channel_id: str,
        user_id: str,
        team_id: Optional[str] = None,
        thread_ts: Optional[str] = None
    ) -> bool:
        """Clear active mapping for the context."""
        key = self.build_context_key(team_id, channel_id, thread_ts, user_id)
        with self.session_factory() as session:
            mapping = session.query(SlackConversationMappingModel).filter(
                SlackConversationMappingModel.context_key == key
            ).first()
            if mapping:
                session.delete(mapping)
                session.commit()
                return True
            return False

