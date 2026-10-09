import os
import io
from typing import Optional, Dict, Any
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import httpx

from app.core.config import settings
from app.core.logging import logger
from app.integrations.legal_qa_client import LegalQAClient, LegalQAAPIError
from app.integrations.slack_mapping_repo import SlackMappingRepository
from app.integrations.slack_formatter import (
    extract_user_query,
    parse_select_command,
    is_list_docs_command,
    is_clear_context_command,
    is_help_command,
    format_slack_answer,
    format_help_message
)
from app.integrations.slack_dedup import EventDeduplicator


class SlackAdapter:
    """
    Slack Bolt Adapter for the Legal Document QA Assistant.
    Translates Slack events/mentions into REST calls to the existing /api/v1 backend.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        app_token: Optional[str] = None,
        api_client: Optional[LegalQAClient] = None,
        mapping_repo: Optional[SlackMappingRepository] = None
    ):
        self.bot_token = bot_token or settings.SLACK_BOT_TOKEN
        self.app_token = app_token or settings.SLACK_APP_TOKEN

        self.api_client = api_client or LegalQAClient(base_url=settings.LEGAL_QA_API_BASE_URL)
        self.mapping_repo = mapping_repo or SlackMappingRepository()
        self.dedup = EventDeduplicator()

        self.app = App(token=self.bot_token)
        self._register_handlers()

    def _register_handlers(self):
        """Register Slack Bolt event listeners."""

        @self.app.event("app_mention")
        def handle_mention(event, say, client):
            self.handle_message_event(event, say, client)

        @self.app.event("message")
        def handle_message(event, say, client):
            # Only respond to direct messages (channel_type == 'im')
            # Channels/groups are handled by app_mention to prevent unsolicited noise
            channel_type = event.get("channel_type")
            subtype = event.get("subtype")

            # Ignore bot messages or message edits
            if subtype in ("bot_message", "message_changed", "message_deleted"):
                return

            if channel_type == "im":
                self.handle_message_event(event, say, client)
            elif event.get("files"):
                # Check if file uploaded in channel with a bot mention or in thread
                self.handle_message_event(event, say, client)

    def handle_message_event(self, event: Dict[str, Any], say, client):
        """Unified handler for mention and DM events."""
        event_id = event.get("client_msg_id") or event.get("event_ts") or event.get("ts")
        if event_id and self.dedup.is_duplicate(str(event_id)):
            logger.info(f"[SlackAdapter] Skipping duplicate event {event_id}")
            return

        channel = event.get("channel")
        user = event.get("user")
        team = event.get("team")
        # thread_ts is only non-None when inside an existing thread
        thread_ts = event.get("thread_ts")
        # reply_ts is used to reply in the existing thread, or start a new thread off the message ts
        reply_ts = thread_ts or event.get("ts")
        raw_text = event.get("text", "")

        # 1. Check for file attachments (PDF upload - Phase C)
        files = event.get("files", [])
        if files:
            self._handle_file_upload(files, channel, user, team, thread_ts, reply_ts, say, client)
            return

        cleaned_text = extract_user_query(raw_text)
        if not cleaned_text:
            say(
                text="Hello! How can I assist you with your legal documents today? Type `help` for instructions.",
                thread_ts=reply_ts
            )
            return

        # 2. Check for Help command
        if is_help_command(cleaned_text):
            say(text=format_help_message(), thread_ts=reply_ts)
            return

        # 3. Check for Reset / Clear context command
        if is_clear_context_command(cleaned_text):
            self.mapping_repo.clear_mapping(
                channel_id=channel,
                user_id=user,
                team_id=team,
                thread_ts=thread_ts
            )
            say(
                text="Active document and conversation session cleared. You can select a document with `select <document_id>` or ask general legal questions.",
                thread_ts=reply_ts
            )
            return

        # 4. Check for List Documents command
        if is_list_docs_command(cleaned_text):
            self._handle_list_documents(channel, reply_ts, say)
            return

        # 5. Check for Select Document command
        target_doc = parse_select_command(cleaned_text)
        if target_doc:
            self._handle_select_document(target_doc, channel, user, team, thread_ts, reply_ts, say)
            return

        # 6. Chat / Ask Question (Phase A & B)
        self._handle_chat_query(cleaned_text, channel, user, team, thread_ts, reply_ts, say)

    def _handle_list_documents(self, channel: str, reply_ts: str, say):
        try:
            docs = self.api_client.list_documents()
            if not docs:
                say(
                    text="No documents have been indexed yet. You can upload a PDF right here in Slack!",
                    thread_ts=reply_ts
                )
                return

            msg_lines = ["*Available Legal Documents:*"]
            for d in docs:
                doc_id = d.get("document_id")
                filename = d.get("original_filename") or d.get("filename")
                pages = d.get("page_count", 0)
                chunks = d.get("chunk_count", 0)
                msg_lines.append(f"• `{doc_id}`: *{filename}* ({pages} pages, {chunks} chunks)")

            msg_lines.append("\nTo query one, type `select <document_id>`.")
            say(text="\n".join(msg_lines), thread_ts=reply_ts)
        except LegalQAAPIError as e:
            say(text=f"⚠️ {e.message}", thread_ts=reply_ts)

    def _handle_select_document(
        self,
        doc_id: str,
        channel: str,
        user: str,
        team: Optional[str],
        thread_ts: Optional[str],
        reply_ts: str,
        say
    ):
        try:
            # Verify document exists in backend
            doc_detail = self.api_client.get_document(doc_id)
            filename = doc_detail.get("original_filename") or doc_detail.get("filename", doc_id)

            # Persist mapping for this user + thread/channel context
            self.mapping_repo.save_mapping(
                channel_id=channel,
                user_id=user,
                team_id=team,
                thread_ts=thread_ts,
                document_id=doc_id,
                conversation_id=None  # Reset conversation to start fresh with this doc
            )

            context_scope = "in this thread" if thread_ts else "in this conversation"
            say(
                text=f"Selected document *{filename}* (`{doc_id}`). You can now ask questions about it {context_scope}!",
                thread_ts=reply_ts
            )
        except LegalQAAPIError as e:
            say(text=f"⚠️ {e.message}", thread_ts=reply_ts)

    def _handle_chat_query(
        self,
        question: str,
        channel: str,
        user: str,
        team: Optional[str],
        thread_ts: Optional[str],
        reply_ts: str,
        say
    ):
        # Retrieve active context for this user and thread
        mapping = self.mapping_repo.get_mapping(
            channel_id=channel,
            user_id=user,
            team_id=team,
            thread_ts=thread_ts
        )

        doc_id = mapping.document_id if mapping else None
        conv_id = mapping.conversation_id if mapping else None

        try:
            chat_res = self.api_client.chat(
                question=question,
                document_id=doc_id,
                conversation_id=conv_id
            )

            # Update conversation ID mapping
            new_conv_id = chat_res.get("conversation_id")
            if new_conv_id is not None and not isinstance(new_conv_id, str):
                new_conv_id = str(new_conv_id) if not hasattr(new_conv_id, "_mock_name") else None

            if new_conv_id and (not conv_id or new_conv_id != conv_id):
                self.mapping_repo.save_mapping(
                    channel_id=channel,
                    user_id=user,
                    team_id=team,
                    thread_ts=thread_ts,
                    document_id=doc_id,
                    conversation_id=new_conv_id
                )

            answer = chat_res.get("answer", "")
            sources = chat_res.get("sources", [])
            returned_doc = chat_res.get("document_id") or doc_id

            formatted = format_slack_answer(
                answer=answer,
                sources=sources,
                document_id=returned_doc
            )

            # If no document was selected and answer was general legal info, give a tip
            if not returned_doc:
                formatted += "\n\n_Tip: To analyze a specific document, type `list docs` and `select <document_id>`, or upload a PDF._"

            say(text=formatted, thread_ts=reply_ts)

        except LegalQAAPIError as e:
            say(text=f"⚠️ {e.message}", thread_ts=reply_ts)

    def _handle_file_upload(
        self,
        files: list,
        channel: str,
        user: str,
        team: Optional[str],
        thread_ts: Optional[str],
        reply_ts: str,
        say,
        client
    ):
        """Download file from Slack, validate PDF, and upload to REST API."""
        for file_info in files:
            file_id = file_info.get("id")
            file_name = file_info.get("name", "document.pdf")
            filetype = file_info.get("filetype", "").lower()
            download_url = file_info.get("url_private_download") or file_info.get("url_private")

            # Validate file format
            if filetype != "pdf" and not file_name.lower().endswith(".pdf"):
                say(
                    text=f"⚠️ File *{file_name}* is not a PDF. Currently only PDF documents are supported for upload in Slack.",
                    thread_ts=reply_ts
                )
                continue

            say(text=f"Processing and indexing *{file_name}*... Please allow a few moments.", thread_ts=reply_ts)

            try:
                # Authenticated download using Slack bot token
                headers = {"Authorization": f"Bearer {self.bot_token}"}
                with httpx.Client(timeout=30.0) as http_client:
                    resp = http_client.get(download_url, headers=headers)
                    resp.raise_for_status()
                    file_bytes = resp.content

                # Upload to existing POST /api/v1/documents
                upload_res = self.api_client.upload_document(
                    file_bytes=file_bytes,
                    filename=file_name
                )

                doc_id = upload_res.get("document_id")
                pages = upload_res.get("page_count", 0)
                chunks = upload_res.get("chunk_count", 0)

                # Bind uploaded document to this user's current thread/context
                self.mapping_repo.save_mapping(
                    channel_id=channel,
                    user_id=user,
                    team_id=team,
                    thread_ts=thread_ts,
                    document_id=doc_id,
                    conversation_id=None
                )

                context_scope = "in this thread" if thread_ts else "in this conversation"
                say(
                    text=(
                        f"✅ Successfully processed and indexed *{file_name}*!\n"
                        f"• Document ID: `{doc_id}`\n"
                        f"• Pages: {pages}\n"
                        f"• Chunks: {chunks}\n\n"
                        f"This document is now set as your active context {context_scope}. Feel free to ask questions!"
                    ),
                    thread_ts=reply_ts
                )

            except LegalQAAPIError as e:
                say(text=f"⚠️ Upload failed: {e.message}", thread_ts=reply_ts)
            except Exception as e:
                logger.error(f"[SlackAdapter] Error downloading/uploading Slack file: {e}")
                say(text="⚠️ Failed to download or process file from Slack.", thread_ts=reply_ts)

    def start_socket_mode(self):
        """Starts the Bolt app in Socket Mode."""
        if not self.app_token:
            raise ValueError("SLACK_APP_TOKEN is required to run Socket Mode.")
        handler = SocketModeHandler(self.app, self.app_token)
        logger.info("Starting Slack Bolt Socket Mode Handler...")
        handler.start()
