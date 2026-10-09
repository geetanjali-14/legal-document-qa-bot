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

