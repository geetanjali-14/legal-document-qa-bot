import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.persistence.database import Base
from app.integrations.slack_adapter import SlackAdapter
from app.integrations.slack_mapping_repo import SlackMappingRepository
from app.integrations.legal_qa_client import LegalQAClient, LegalQAAPIError


@pytest.fixture
def mock_api_client():
    client = MagicMock(spec=LegalQAClient)
    return client


@pytest.fixture
def test_mapping_repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return SlackMappingRepository(session_factory=session_factory)


@pytest.fixture
def slack_adapter(mock_api_client, test_mapping_repo):
    with patch("app.integrations.slack_adapter.App") as mock_bolt_app:
        adapter = SlackAdapter(
            bot_token="xoxb-mock-token",
            app_token="xapp-mock-token",
            api_client=mock_api_client,
            mapping_repo=test_mapping_repo
        )
        return adapter


def test_mention_without_document(slack_adapter, mock_api_client):
    mock_api_client.chat.return_value = {
        "answer": "A non-disclosure agreement protects confidential information.",
        "conversation_id": "conv_general_123",
        "document_id": None,
        "sources": []
    }

    say_mock = MagicMock()
    event = {
        "text": "<@U_BOT123> What is an NDA?",
        "channel": "C01",
        "user": "U01",
        "ts": "1678900000.01",
        "client_msg_id": "msg_001"
    }

    slack_adapter.handle_message_event(event, say_mock, client=MagicMock())

    mock_api_client.chat.assert_called_once_with(
        question="What is an NDA?",
        document_id=None,
        conversation_id=None
    )
    say_mock.assert_called_once()
    sent_text = say_mock.call_args[1]["text"]
    assert "A non-disclosure agreement protects confidential information." in sent_text
    assert "Tip: To analyze a specific document" in sent_text


def test_select_document_and_followup_preserves_conversation(slack_adapter, mock_api_client):
    # 1. User selects document
    mock_api_client.get_document.return_value = {
        "document_id": "doc_rental_99",
        "filename": "doc_rental_99_rental.pdf",
        "original_filename": "rental.pdf"
    }

    say_mock = MagicMock()
    select_event = {
        "text": "<@U_BOT123> select doc_rental_99",
        "channel": "C01",
        "user": "U01",
        "ts": "1678900000.02",
        "client_msg_id": "msg_002"
    }
    slack_adapter.handle_message_event(select_event, say_mock, client=MagicMock())
    assert "Selected document *rental.pdf*" in say_mock.call_args[1]["text"]

    # 2. First question with selected doc
    mock_api_client.chat.return_value = {
        "answer": "Notice period is 30 days.",
        "conversation_id": "conv_session_abc",
        "document_id": "doc_rental_99",
        "sources": [{"page_number": 2, "section": "Clause 4", "clause_number": "4"}]
    }

    say_q1 = MagicMock()
    q1_event = {
        "text": "<@U_BOT123> What is the notice period?",
        "channel": "C01",
        "user": "U01",
        "ts": "1678900000.03",
        "client_msg_id": "msg_003"
    }
    slack_adapter.handle_message_event(q1_event, say_q1, client=MagicMock())

    mock_api_client.chat.assert_called_with(
        question="What is the notice period?",
        document_id="doc_rental_99",
        conversation_id=None
    )
    assert "*Page 2* — Clause 4 (Clause 4)" in say_q1.call_args[1]["text"]

    # 3. Follow-up question: must preserve conversation_id "conv_session_abc"
    mock_api_client.chat.return_value = {
        "answer": "Either landlord or tenant may terminate.",
        "conversation_id": "conv_session_abc",
        "document_id": "doc_rental_99",
        "sources": [{"page_number": 2, "section": "Clause 4", "clause_number": "4.2"}]
    }

    say_q2 = MagicMock()
    q2_event = {
        "text": "<@U_BOT123> Who can terminate it?",
        "channel": "C01",
        "user": "U01",
        "ts": "1678900000.04",
        "client_msg_id": "msg_004"
    }
    slack_adapter.handle_message_event(q2_event, say_q2, client=MagicMock())

    mock_api_client.chat.assert_called_with(
        question="Who can terminate it?",
        document_id="doc_rental_99",
        conversation_id="conv_session_abc"
    )


def test_api_failure_returns_user_friendly_error(slack_adapter, mock_api_client):
    mock_api_client.chat.side_effect = LegalQAAPIError("The Legal QA service is currently unreachable. Please try again shortly.")

    say_mock = MagicMock()
    event = {
        "text": "<@U_BOT123> What is the rent?",
        "channel": "C01",
        "user": "U01",
        "ts": "1678900000.05",
        "client_msg_id": "msg_005"
    }

    slack_adapter.handle_message_event(event, say_mock, client=MagicMock())

    say_mock.assert_called_once()
    error_msg = say_mock.call_args[1]["text"]
    assert "⚠️ The Legal QA service is currently unreachable" in error_msg
    # Ensure no internal stack traces or raw keys leaked
    assert "Traceback" not in error_msg
    assert "gsk_" not in error_msg


def test_duplicate_event_handling(slack_adapter, mock_api_client):
    mock_api_client.chat.return_value = {
        "answer": "Answer 1",
        "conversation_id": "c1",
        "document_id": None,
        "sources": []
    }

    say_mock = MagicMock()
    event = {
        "text": "<@U_BOT123> Hello",
        "channel": "C01",
        "user": "U01",
        "ts": "1678900000.06",
        "client_msg_id": "msg_dup_1"
    }

    # First delivery
    slack_adapter.handle_message_event(event, say_mock, client=MagicMock())
    assert say_mock.call_count == 1

    # Retried delivery with same client_msg_id
    slack_adapter.handle_message_event(event, say_mock, client=MagicMock())
    # Should still be 1 (ignored second call)
    assert say_mock.call_count == 1


@patch("httpx.Client")
def test_pdf_upload_handling(mock_httpx_cls, slack_adapter, mock_api_client):
    mock_http = MagicMock()
    mock_httpx_cls.return_value.__enter__.return_value = mock_http
    mock_http.get.return_value.status_code = 200
    mock_http.get.return_value.content = b"%PDF-1.4 mock pdf content"

    mock_api_client.upload_document.return_value = {
        "document_id": "doc_pdf_123",
        "filename": "lease.pdf",
        "status": "processed",
        "page_count": 5,
        "chunk_count": 30
    }

    say_mock = MagicMock()
    file_event = {
        "channel": "C01",
        "user": "U_ALICE",
        "ts": "1678900000.07",
        "client_msg_id": "msg_file_001",
        "files": [
            {
                "id": "F123",
                "name": "lease.pdf",
                "filetype": "pdf",
                "url_private_download": "https://slack.com/files/download"
            }
        ]
    }

    slack_adapter.handle_message_event(file_event, say_mock, client=MagicMock())

    # Verify upload was called
    mock_api_client.upload_document.assert_called_once_with(
        file_bytes=b"%PDF-1.4 mock pdf content",
        filename="lease.pdf"
    )

    # Check confirmation message
    confirmation = say_mock.call_args[1]["text"]
    assert "Successfully processed and indexed *lease.pdf*" in confirmation
    assert "doc_pdf_123" in confirmation
    assert "Pages: 5" in confirmation
    assert "Chunks: 30" in confirmation


@patch("httpx.Client")
def test_dm_upload_and_separate_toplevel_message_followup(mock_httpx_cls, slack_adapter, mock_api_client):
    """
    Regression test for reported bug:
    1. User uploads PDF in DM (top-level message, thread_ts=None, ts="1678900001.01").
    2. Bot indexes and confirms document context.
    3. User asks question in a separate top-level DM message (thread_ts=None, ts="1678900005.02").
    4. Must retrieve the active document ID and pass it to /api/v1/chat.
    """
    mock_http = MagicMock()
    mock_httpx_cls.return_value.__enter__.return_value = mock_http
    mock_http.get.return_value.status_code = 200
    mock_http.get.return_value.content = b"%PDF-1.4 mock policy content"

    mock_api_client.upload_document.return_value = {
        "document_id": "doc_03f8339dc570",
        "filename": "Annual Increment Policy.pdf",
        "status": "processed",
        "page_count": 5,
        "chunk_count": 37
    }

    # Step 1: Upload in DM (channel_type="im", no thread_ts, only ts, team field might be omitted by Slack in file upload)
    dm_channel = "D_USER_DIRECT"
    user_id = "U_EMPLOYEE"
    say_upload = MagicMock()
    upload_event = {
        "channel": dm_channel,
        "channel_type": "im",
        "user": user_id,
        "ts": "1678900001.01",
        "client_msg_id": "msg_dm_upload",
        # team field might not be on file_share message
        "files": [
            {
                "id": "F_POLICY",
                "name": "Annual Increment Policy.pdf",
                "filetype": "pdf",
                "url_private_download": "https://slack.com/files/policy.pdf"
            }
        ]
    }
    slack_adapter.handle_message_event(upload_event, say_upload, client=MagicMock())
    assert "doc_03f8339dc570" in say_upload.call_args[1]["text"]

    # Step 2: Separate top-level DM message from same user asking what doc is about
    # Note: ts is different, thread_ts is None, and team_id is explicitly set by Slack
    mock_api_client.chat.return_value = {
        "answer": "This document outlines the guidelines for annual employee increments and merit raises.",
        "conversation_id": "conv_dm_session_1",
        "document_id": "doc_03f8339dc570",
        "sources": [{"page_number": 1, "section": "1. Purpose", "clause_number": "1.1"}]
    }

    say_q1 = MagicMock()
    q1_event = {
        "channel": dm_channel,
        "channel_type": "im",
        "user": user_id,
        "team": "T_WORKSPACE_123",  # Explicit team
        "ts": "1678900005.02",      # Different timestamp!
        "client_msg_id": "msg_dm_q1",
        "text": "What is this document about?"
    }
    slack_adapter.handle_message_event(q1_event, say_q1, client=MagicMock(), team_id="T_WORKSPACE_123")

    # Verify chat was called WITH the uploaded document_id!
    mock_api_client.chat.assert_called_once_with(
        question="What is this document about?",
        document_id="doc_03f8339dc570",
        conversation_id=None
    )
    answer_text = say_q1.call_args[1]["text"]
    assert "This document outlines the guidelines" in answer_text
    assert "*Page 1* — 1. Purpose" in answer_text
    # Document context is now kept clean and hidden from ordinary chat answers
    assert "_Document Context:" not in answer_text


def test_thread_replies_and_multiuser_isolation(slack_adapter, mock_api_client):
    """
    Verifies:
    1. Thread replies preserve thread-specific context.
    2. Other users in the same channel/thread do NOT share context.
    3. 'clear' removes the context.
    """
    channel = "C_LEGAL_TEAM"
    thread_root = "1678900100.00"
    user_alice = "U_ALICE"
    user_bob = "U_BOB"

    # Alice selects document in thread
    mock_api_client.get_document.return_value = {
        "document_id": "doc_alice_master_service",
        "filename": "msa.pdf",
        "original_filename": "msa.pdf"
    }
    say_alice_select = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "user": user_alice,
        "thread_ts": thread_root,
        "ts": "1678900101.00",
        "client_msg_id": "msg_alice_sel",
        "text": "<@U_BOT123> select doc_alice_master_service"
    }, say_alice_select, client=MagicMock())

    # Alice asks a question in the thread
    mock_api_client.chat.return_value = {
        "answer": "Payment terms are Net 30.",
        "conversation_id": "conv_alice_msa",
        "document_id": "doc_alice_master_service",
        "sources": []
    }
    say_alice_q = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "user": user_alice,
        "thread_ts": thread_root,
        "ts": "1678900105.00",
        "client_msg_id": "msg_alice_q1",
        "text": "<@U_BOT123> What are the payment terms?"
    }, say_alice_q, client=MagicMock())

    mock_api_client.chat.assert_called_with(
        question="What are the payment terms?",
        document_id="doc_alice_master_service",
        conversation_id=None
    )

    # Bob asks in the same thread: Bob has NO document selected!
    mock_api_client.chat.reset_mock()
    mock_api_client.chat.return_value = {
        "answer": "Payment terms define when invoices must be settled.",
        "conversation_id": "conv_bob_gen",
        "document_id": None,
        "sources": []
    }
    say_bob_q = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "user": user_bob,
        "thread_ts": thread_root,
        "ts": "1678900110.00",
        "client_msg_id": "msg_bob_q1",
        "text": "<@U_BOT123> Explain payment terms"
    }, say_bob_q, client=MagicMock())

    # Bob's query must NOT have doc_alice_master_service!
    mock_api_client.chat.assert_called_with(
        question="Explain payment terms",
        document_id=None,
        conversation_id=None
    )

    # Alice clears context
    say_alice_clear = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "user": user_alice,
        "thread_ts": thread_root,
        "ts": "1678900120.00",
        "client_msg_id": "msg_alice_clr",
        "text": "<@U_BOT123> clear"
    }, say_alice_clear, client=MagicMock())
    assert "Active document and conversation session cleared" in say_alice_clear.call_args[1]["text"]

    # Alice's subsequent query now has no document
    mock_api_client.chat.reset_mock()
    mock_api_client.chat.return_value = {
        "answer": "General legal information.",
        "conversation_id": "conv_alice_after_clear",
        "document_id": None,
        "sources": []
    }
    say_alice_after = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "user": user_alice,
        "thread_ts": thread_root,
        "ts": "1678900125.00",
        "client_msg_id": "msg_alice_q2",
        "text": "<@U_BOT123> What is an SLA?"
    }, say_alice_after, client=MagicMock())

    mock_api_client.chat.assert_called_with(
        question="What is an SLA?",
        document_id=None,
        conversation_id=None
    )


@patch("httpx.Client")
def test_upload_pdf_after_general_chat_clears_stale_conversation(mock_httpx_cls, slack_adapter, mock_api_client):
    """
    Verifies that when a user previously engaged in general legal chat (generating a conversation_id
    with no attached document), and later uploads a PDF, the stale conversation_id is purged
    so subsequent questions on the document do not fail with mismatched conversation errors.
    """
    mock_http = MagicMock()
    mock_httpx_cls.return_value.__enter__.return_value = mock_http
    mock_http.get.return_value.status_code = 200
    mock_http.get.return_value.content = b"%PDF-1.4 mock content"

    channel = "D0C7JEU5NKZ"
    user = "U0C83FCHPL4"
    team = "T0C7THV2CJF"

    # Step 1: User asks general question, gets conv_acb4215d19644490 (no document)
    mock_api_client.chat.return_value = {
        "answer": "General overview of contract law.",
        "conversation_id": "conv_acb4215d19644490",
        "document_id": None,
        "sources": []
    }
    say_gen = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "channel_type": "im",
        "user": user,
        "team": team,
        "ts": "1791533000.01",
        "client_msg_id": "msg_gen_01",
        "text": "What is an NDA?"
    }, say_gen, client=MagicMock(), team_id=team)

    mapping = slack_adapter.mapping_repo.get_mapping(channel, user, team_id=team)
    assert mapping.conversation_id == "conv_acb4215d19644490"
    assert mapping.document_id is None

    # Step 2: User uploads Annual Increment Policy.pdf
    mock_api_client.upload_document.return_value = {
        "document_id": "doc_03f8339dc570",
        "filename": "Annual Increment Policy.pdf",
        "status": "processed",
        "page_count": 5,
        "chunk_count": 37
    }
    say_upload = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "channel_type": "im",
        "user": user,
        "team": team,
        "ts": "1791533100.02",
        "client_msg_id": "msg_upload_02",
        "files": [{
            "id": "F_001",
            "name": "Annual Increment Policy.pdf",
            "filetype": "pdf",
            "url_private_download": "https://slack.com/files/policy.pdf"
        }]
    }, say_upload, client=MagicMock(), team_id=team)

    # Repository should now reflect doc_03f8339dc570 and NO stale conversation_id!
    mapping_after_upload = slack_adapter.mapping_repo.get_mapping(channel, user, team_id=team)
    assert mapping_after_upload.document_id == "doc_03f8339dc570"
    assert mapping_after_upload.conversation_id is None

    # Step 3: User asks "What is this document about?"
    mock_api_client.chat.reset_mock()
    mock_api_client.chat.return_value = {
        "answer": "The document covers annual salary increments.",
        "conversation_id": "conv_fresh_doc_session_999",
        "document_id": "doc_03f8339dc570",
        "sources": []
    }
    say_q = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "channel_type": "im",
        "user": user,
        "team": team,
        "ts": "1791533200.03",
        "client_msg_id": "msg_doc_q_03",
        "text": "What is this document about?"
    }, say_q, client=MagicMock(), team_id=team)

    mock_api_client.chat.assert_called_once_with(
        question="What is this document about?",
        document_id="doc_03f8339dc570",
        conversation_id=None
    )


def test_conversation_mismatch_self_healing_retry(slack_adapter, mock_api_client):
    """
    Verifies that if for any reason a stale conversation ID produces a 400 mismatch error from the API,
    the SlackAdapter automatically catches the error, clears the invalid conversation ID,
    and successfully retries the chat request with conversation_id=None.
    """
    from app.integrations.legal_qa_client import LegalQAAPIError

    channel = "D0C7JEU5NKZ"
    user = "U0C83FCHPL4"
    team = "T0C7THV2CJF"

    # Prepopulate mapping with mismatched state
    slack_adapter.mapping_repo.save_mapping(
        channel_id=channel,
        user_id=user,
        team_id=team,
        document_id="doc_03f8339dc570",
        conversation_id="conv_mismatched_old"
    )

    # First call fails with 400 mismatch, second call succeeds
    mock_api_client.chat.side_effect = [
        LegalQAAPIError(
            status_code=400,
            message="Conversation 'conv_mismatched_old' does not belong to document 'doc_03f8339dc570'. Mismatched document/conversation requests are rejected to maintain document isolation."
        ),
        {
            "answer": "This policy specifies employee increment cycles.",
            "conversation_id": "conv_healed_new_123",
            "document_id": "doc_03f8339dc570",
            "sources": []
        }
    ]

    say_mock = MagicMock()
    slack_adapter.handle_message_event({
        "channel": channel,
        "channel_type": "im",
        "user": user,
        "team": team,
        "ts": "1791533500.01",
        "client_msg_id": "msg_heal_01",
        "text": "What is this document about?"
    }, say_mock, client=MagicMock(), team_id=team)

    assert mock_api_client.chat.call_count == 2
    # Verify second call had conversation_id=None
    second_call_args = mock_api_client.chat.call_args_list[1]
    assert second_call_args[1]["conversation_id"] is None
    assert second_call_args[1]["document_id"] == "doc_03f8339dc570"

    # Verify user received the actual answer without seeing an error
    final_text = say_mock.call_args[1]["text"]
    assert "This policy specifies employee increment cycles." in final_text
    assert "Mismatched" not in final_text



