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
from app.integrations.contracts import PlatformIncomingMessage, PlatformAction
from app.integrations.coordinator import IntegrationCoordinator


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
        mapping_repo: Optional[SlackMappingRepository] = None,
        coordinator: Optional[IntegrationCoordinator] = None
    ):
        self.bot_token = bot_token or settings.SLACK_BOT_TOKEN
        self.app_token = app_token or settings.SLACK_APP_TOKEN

        self.api_client = api_client or LegalQAClient(base_url=settings.LEGAL_QA_API_BASE_URL)
        self.mapping_repo = mapping_repo or SlackMappingRepository()
        self.dedup = EventDeduplicator()

        self.coordinator = coordinator or IntegrationCoordinator(
            api_client=self.api_client,
            mapping_repo=self.mapping_repo,
            dedup=self.dedup
        )

        self.app = App(token=self.bot_token)
        self._register_handlers()

    def _register_handlers(self):
        """Register Slack Bolt event listeners."""

        @self.app.event("app_mention")
        def handle_mention(event, context, say, client):
            team_id = getattr(context, "team_id", None) or event.get("team")
            self.handle_message_event(event, say, client, team_id=team_id)

        @self.app.event("message")
        def handle_message(event, context, say, client):
            # Only respond to direct messages (channel_type == 'im') or file shares
            # Channels/groups are handled by app_mention to prevent unsolicited noise
            channel_type = event.get("channel_type")
            subtype = event.get("subtype")

            # Ignore bot messages or message edits
            if subtype in ("bot_message", "message_changed", "message_deleted"):
                return

            team_id = getattr(context, "team_id", None) or event.get("team")
            if channel_type == "im":
                self.handle_message_event(event, say, client, team_id=team_id)
            elif event.get("files"):
                # Check if file uploaded in channel with a bot mention or in thread
                self.handle_message_event(event, say, client, team_id=team_id)

    def handle_message_event(self, event: Dict[str, Any], say, client, team_id: Optional[str] = None):
        """Unified handler for mention and DM events."""
        event_id = event.get("client_msg_id") or event.get("event_ts") or event.get("ts")
        if event_id and self.dedup.is_duplicate(str(event_id)):
            logger.info(f"[SlackAdapter] Skipping duplicate event {event_id}")
            return

        channel = event.get("channel")
        user = event.get("user")
        team = team_id or event.get("team")
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
        incoming_msg = PlatformIncomingMessage(
            platform="slack",
            tenant_id=team,
            channel_id=channel,
            thread_id=thread_ts,
            user_id=user,
            text=cleaned_text,
            event_id=None  # Already deduplicated above by SlackAdapter
        )

        response = self.coordinator.process_message(incoming_msg)
        if not response:
            return

        # Format and deliver response to Slack
        if response.action == PlatformAction.HELP:
            if not cleaned_text:
                say(text=response.text, thread_ts=reply_ts)
            else:
                say(text=format_help_message(), thread_ts=reply_ts)

        elif response.action == PlatformAction.CLEAR_CONTEXT:
            say(text=response.text, thread_ts=reply_ts)

        elif response.action == PlatformAction.LIST_DOCUMENTS:
            docs = response.metadata.get("documents", [])
            if not docs:
                say(
                    text="No documents have been indexed yet. You can upload a PDF right here in Slack!",
                    thread_ts=reply_ts
                )
            else:
                msg_lines = ["*Available Legal Documents:*"]
                for d in docs:
                    doc_id = d.get("document_id")
                    filename = d.get("original_filename") or d.get("filename")
                    pages = d.get("page_count", 0)
                    chunks = d.get("chunk_count", 0)
                    msg_lines.append(f"• `{doc_id}`: *{filename}* ({pages} pages, {chunks} chunks)")
                msg_lines.append("\nTo query one, type `select <document_id>`.")
                say(text="\n".join(msg_lines), thread_ts=reply_ts)

        elif response.action == PlatformAction.SELECT_DOCUMENT:
            filename = response.metadata.get("filename", response.document_id)
            context_scope = "in this thread" if thread_ts else "in this conversation"
            say(
                text=f"Selected document *{filename}* (`{response.document_id}`). You can now ask questions about it {context_scope}!",
                thread_ts=reply_ts
            )

        elif response.action == PlatformAction.ANSWER:
            formatted = format_slack_answer(
                answer=response.text,
                sources=response.sources,
                document_id=response.document_id
            )
            if not response.document_id:
                formatted += "\n\n_Tip: To analyze a specific document, type `list docs` and `select <document_id>`, or upload a PDF._"
            say(text=formatted, thread_ts=reply_ts)

        elif response.action == PlatformAction.ERROR:
            say(text=f"⚠️ {response.text}", thread_ts=reply_ts)

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

                # Delegate upload and context binding to coordinator
                upload_msg = PlatformIncomingMessage(
                    platform="slack",
                    tenant_id=team,
                    channel_id=channel,
                    thread_id=thread_ts,
                    user_id=user,
                    file_bytes=file_bytes,
                    filename=file_name
                )
                upload_resp = self.coordinator.process_message(upload_msg)

                if not upload_resp or upload_resp.action == PlatformAction.ERROR:
                    err_msg = upload_resp.text if upload_resp else "Failed to process file from Slack."
                    say(text=f"⚠️ {err_msg}", thread_ts=reply_ts)
                    continue

                doc_id = upload_resp.document_id
                pages = upload_resp.metadata.get("page_count", 0)
                chunks = upload_resp.metadata.get("chunk_count", 0)

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
