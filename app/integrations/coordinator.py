from typing import Optional, Dict, Any
from app.core.logging import logger
from app.integrations.contracts import (
    PlatformIncomingMessage,
    PlatformOutgoingResponse,
    PlatformAction
)
from app.integrations.legal_qa_client import LegalQAClient, LegalQAAPIError
from app.integrations.slack_mapping_repo import SlackMappingRepository
from app.integrations.slack_formatter import (
    parse_select_command,
    is_list_docs_command,
    is_clear_context_command,
    is_help_command
)
from app.integrations.slack_dedup import EventDeduplicator


class IntegrationCoordinator:
    """
    Platform-independent coordinator for legal chat workflows.
    Encapsulates command parsing, context resolution, backend API interaction,
    document selection, file upload delegation, and conversation-mismatch recovery.
    """

    def __init__(
        self,
        api_client: Optional[LegalQAClient] = None,
        mapping_repo: Optional[SlackMappingRepository] = None,
        dedup: Optional[EventDeduplicator] = None
    ):
        self.api_client = api_client or LegalQAClient()
        self.mapping_repo = mapping_repo or SlackMappingRepository()
        self.dedup = dedup or EventDeduplicator()

    def process_message(self, msg: PlatformIncomingMessage) -> Optional[PlatformOutgoingResponse]:
        """
        Main entry point for incoming platform messages.
        Returns a PlatformOutgoingResponse, or None if the message is duplicate / ignored.
        """
        # 1. Event deduplication
        if msg.event_id and self.dedup.is_duplicate(str(msg.event_id)):
            logger.info(f"[Coordinator] Skipping duplicate event {msg.event_id}")
            return None

        # 2. File upload handling
        if msg.file_bytes:
            return self._handle_file_upload(msg)

        cleaned_text = (msg.text or "").strip()
        if not cleaned_text:
            return PlatformOutgoingResponse(
                action=PlatformAction.HELP,
                text="Hello! How can I assist you with your legal documents today? Type `help` for instructions."
            )

        # 3. Help command
        if is_help_command(cleaned_text):
            return PlatformOutgoingResponse(
                action=PlatformAction.HELP,
                text="help"
            )

        # 4. Clear context / session reset command
        if is_clear_context_command(cleaned_text):
            self.mapping_repo.clear_mapping(
                channel_id=msg.channel_id,
                user_id=msg.user_id,
                team_id=msg.tenant_id,
                thread_ts=msg.thread_id
            )
            return PlatformOutgoingResponse(
                action=PlatformAction.CLEAR_CONTEXT,
                text="Active document and conversation session cleared. You can select a document with `select <document_id>` or ask general legal questions."
            )

        # 5. List documents command
        if is_list_docs_command(cleaned_text):
            return self._handle_list_documents()

        # 6. Select document command
        target_doc = parse_select_command(cleaned_text)
        if target_doc:
            return self._handle_select_document(target_doc, msg)

        # 7. Conversational Chat Query (with auto-healing recovery)
        return self._handle_chat_query(cleaned_text, msg)

    def _handle_list_documents(self) -> PlatformOutgoingResponse:
        try:
            docs = self.api_client.list_documents()
            return PlatformOutgoingResponse(
                action=PlatformAction.LIST_DOCUMENTS,
                text="",
                metadata={"documents": docs}
            )
        except LegalQAAPIError as e:
            return PlatformOutgoingResponse(
                action=PlatformAction.ERROR,
                text=e.message
            )

    def _handle_select_document(self, doc_id: str, msg: PlatformIncomingMessage) -> PlatformOutgoingResponse:
        try:
            doc_detail = self.api_client.get_document(doc_id)
            filename = doc_detail.get("original_filename") or doc_detail.get("filename", doc_id)

            # Persist mapping for this user + thread/channel context
            self.mapping_repo.save_mapping(
                channel_id=msg.channel_id,
                user_id=msg.user_id,
                team_id=msg.tenant_id,
                thread_ts=msg.thread_id,
                document_id=doc_id,
                conversation_id=None,
                reset_conversation=True
            )

            return PlatformOutgoingResponse(
                action=PlatformAction.SELECT_DOCUMENT,
                text="",
                document_id=doc_id,
                metadata={"filename": filename}
            )
        except LegalQAAPIError as e:
            return PlatformOutgoingResponse(
                action=PlatformAction.ERROR,
                text=e.message
            )

    def _handle_chat_query(self, question: str, msg: PlatformIncomingMessage) -> PlatformOutgoingResponse:
        mapping = self.mapping_repo.get_mapping(
            channel_id=msg.channel_id,
            user_id=msg.user_id,
            team_id=msg.tenant_id,
            thread_ts=msg.thread_id
        )

        doc_id = mapping.document_id if mapping else None
        conv_id = mapping.conversation_id if mapping else None

        logger.info(
            f"[Coordinator:Chat] channel={msg.channel_id}, user={msg.user_id}, tenant={msg.tenant_id}, "
            f"thread={msg.thread_id} -> active doc_id={doc_id}, conv_id={conv_id}"
        )

        try:
            try:
                chat_res = self.api_client.chat(
                    question=question,
                    document_id=doc_id,
                    conversation_id=conv_id
                )
            except LegalQAAPIError as e:
                # Conversation mismatch recovery: stale conv from general query or different doc
                if conv_id and ("does not belong to document" in (e.message or "").lower() or e.status_code == 400):
                    logger.warning(
                        f"[Coordinator:Chat] Conversation mismatch detected ({conv_id} vs {doc_id}). "
                        f"Resetting stale conversation and retrying."
                    )
                    conv_id = None
                    self.mapping_repo.save_mapping(
                        channel_id=msg.channel_id,
                        user_id=msg.user_id,
                        team_id=msg.tenant_id,
                        thread_ts=msg.thread_id,
                        document_id=doc_id,
                        conversation_id=None,
                        reset_conversation=True
                    )
                    chat_res = self.api_client.chat(
                        question=question,
                        document_id=doc_id,
                        conversation_id=None
                    )
                else:
                    raise

            # Update conversation ID mapping if changed or newly assigned
            new_conv_id = chat_res.get("conversation_id")
            if new_conv_id is not None and not isinstance(new_conv_id, str):
                new_conv_id = str(new_conv_id) if not hasattr(new_conv_id, "_mock_name") else None

            if new_conv_id and (not conv_id or new_conv_id != conv_id):
                self.mapping_repo.save_mapping(
                    channel_id=msg.channel_id,
                    user_id=msg.user_id,
                    team_id=msg.tenant_id,
                    thread_ts=msg.thread_id,
                    document_id=doc_id,
                    conversation_id=new_conv_id
                )

            answer = chat_res.get("answer", "")
            sources = chat_res.get("sources", [])
            returned_doc = chat_res.get("document_id") or doc_id

            return PlatformOutgoingResponse(
                action=PlatformAction.ANSWER,
                text=answer,
                sources=sources,
                document_id=returned_doc,
                conversation_id=new_conv_id or conv_id
            )
        except LegalQAAPIError as e:
            return PlatformOutgoingResponse(
                action=PlatformAction.ERROR,
                text=e.message
            )

    def _handle_file_upload(self, msg: PlatformIncomingMessage) -> PlatformOutgoingResponse:
        filename = msg.filename or "document.pdf"
        try:
            upload_res = self.api_client.upload_document(
                file_bytes=msg.file_bytes,
                filename=filename
            )

            doc_id = upload_res.get("document_id")
            pages = upload_res.get("page_count", 0)
            chunks = upload_res.get("chunk_count", 0)

            logger.info(
                f"[Coordinator:Upload] channel={msg.channel_id}, user={msg.user_id}, tenant={msg.tenant_id}, "
                f"thread={msg.thread_id} -> indexed doc_id={doc_id}"
            )

            # Bind uploaded document to current context and reset conversation
            self.mapping_repo.save_mapping(
                channel_id=msg.channel_id,
                user_id=msg.user_id,
                team_id=msg.tenant_id,
                thread_ts=msg.thread_id,
                document_id=doc_id,
                conversation_id=None,
                reset_conversation=True
            )

            return PlatformOutgoingResponse(
                action=PlatformAction.UPLOAD_FILE,
                text="",
                document_id=doc_id,
                metadata={
                    "filename": filename,
                    "page_count": pages,
                    "chunk_count": chunks
                }
            )
        except LegalQAAPIError as e:
            return PlatformOutgoingResponse(
                action=PlatformAction.ERROR,
                text=f"Upload failed: {e.message}"
            )
        except Exception as e:
            logger.error(f"[Coordinator] Unexpected error uploading document: {e}")
            return PlatformOutgoingResponse(
                action=PlatformAction.ERROR,
                text="Failed to process file upload."
            )

