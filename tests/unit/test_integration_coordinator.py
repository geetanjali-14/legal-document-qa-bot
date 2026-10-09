import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.persistence.database import Base
from app.integrations.slack_mapping_repo import SlackMappingRepository
from app.integrations.legal_qa_client import LegalQAClient, LegalQAAPIError
from app.integrations.contracts import PlatformIncomingMessage, PlatformAction
from app.integrations.coordinator import IntegrationCoordinator


@pytest.fixture
def in_memory_repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return SlackMappingRepository(session_factory=session_factory)


@pytest.fixture
def mock_client():
    return MagicMock(spec=LegalQAClient)


@pytest.fixture
def coordinator(mock_client, in_memory_repo):
    return IntegrationCoordinator(
        api_client=mock_client,
        mapping_repo=in_memory_repo
    )


def test_tenant_isolation_fallback_never_crosses_workspace(in_memory_repo):
    """
    Verifies that when workspace T_A and workspace T_B have identical channel and user IDs,
    a lookup for T_A never matches or inherits document/conversation context from T_B.
    """
    channel = "C_SHARED_NAME"
    user = "U_SAM"

    # Workspace A saves doc_A
    in_memory_repo.save_mapping(
        channel_id=channel,
        user_id=user,
        team_id="T_WORKSPACE_A",
        document_id="doc_alpha_111",
        conversation_id="conv_alpha_111"
    )

    # Workspace B query for same channel/user must NOT return Workspace A's doc
    mapping_b = in_memory_repo.get_mapping(
        channel_id=channel,
        user_id=user,
        team_id="T_WORKSPACE_B"
    )
    assert mapping_b is None

    # Workspace A query for same channel/user returns Workspace A's doc
    mapping_a = in_memory_repo.get_mapping(
        channel_id=channel,
        user_id=user,
        team_id="T_WORKSPACE_A"
    )
    assert mapping_a is not None
    assert mapping_a.document_id == "doc_alpha_111"
    assert mapping_a.conversation_id == "conv_alpha_111"


def test_coordinator_select_document_and_followup(coordinator, mock_client):
    """
    Verifies document selection via coordinator followed by query with persistent conversation ID.
    """
    mock_client.get_document.return_value = {
        "document_id": "doc_nda_99",
        "filename": "nda.pdf",
        "original_filename": "Mutual_NDA.pdf"
    }

    # 1. Select document
    msg_select = PlatformIncomingMessage(
        platform="slack",
        tenant_id="T_CORP",
        channel_id="C_LEGAL",
        user_id="U_BOB",
        text="select doc_nda_99"
    )
    resp_select = coordinator.process_message(msg_select)
    assert resp_select.action == PlatformAction.SELECT_DOCUMENT
    assert resp_select.document_id == "doc_nda_99"
    assert resp_select.metadata["filename"] == "Mutual_NDA.pdf"

    # 2. Ask first question
    mock_client.chat.return_value = {
        "answer": "NDA term is 3 years.",
        "conversation_id": "conv_nda_session_1",
        "document_id": "doc_nda_99",
        "sources": [{"page_number": 1, "section": "Term"}]
    }
    msg_q1 = PlatformIncomingMessage(
        platform="slack",
        tenant_id="T_CORP",
        channel_id="C_LEGAL",
        user_id="U_BOB",
        text="What is the agreement term?"
    )
    resp_q1 = coordinator.process_message(msg_q1)
    assert resp_q1.action == PlatformAction.ANSWER
    assert resp_q1.text == "NDA term is 3 years."
    assert resp_q1.document_id == "doc_nda_99"
    assert resp_q1.conversation_id == "conv_nda_session_1"
    mock_client.chat.assert_called_with(
        question="What is the agreement term?",
        document_id="doc_nda_99",
        conversation_id=None
    )

    # 3. Follow-up preserves conversation_id
    mock_client.chat.return_value = {
        "answer": "Yes, surviving obligations last for 2 additional years.",
        "conversation_id": "conv_nda_session_1",
        "document_id": "doc_nda_99",
        "sources": []
    }
    msg_q2 = PlatformIncomingMessage(
        platform="slack",
        tenant_id="T_CORP",
        channel_id="C_LEGAL",
        user_id="U_BOB",
        text="Do obligations survive termination?"
    )
    resp_q2 = coordinator.process_message(msg_q2)
    assert resp_q2.action == PlatformAction.ANSWER
    mock_client.chat.assert_called_with(
        question="Do obligations survive termination?",
        document_id="doc_nda_99",
        conversation_id="conv_nda_session_1"
    )


def test_coordinator_mismatch_self_healing_recovery(coordinator, mock_client, in_memory_repo):
    """
    Verifies that if chat returns 400 conversation mismatch, the coordinator
    clears conversation_id and retries once with conversation_id=None.
    """
    tenant = "T_LEGAL"
    channel = "C_TEST"
    user = "U_ALICE"

    # Save mismatched state
    in_memory_repo.save_mapping(
        channel_id=channel,
        user_id=user,
        team_id=tenant,
        document_id="doc_current_100",
        conversation_id="conv_stale_old"
    )

    mock_client.chat.side_effect = [
        LegalQAAPIError(
            status_code=400,
            message="Conversation 'conv_stale_old' does not belong to document 'doc_current_100'."
        ),
        {
            "answer": "Retried answer with healed session.",
            "conversation_id": "conv_healed_fresh",
            "document_id": "doc_current_100",
            "sources": []
        }
    ]

    msg = PlatformIncomingMessage(
        platform="slack",
        tenant_id=tenant,
        channel_id=channel,
        user_id=user,
        text="Explain Section 2"
    )
    resp = coordinator.process_message(msg)

    assert resp.action == PlatformAction.ANSWER
    assert resp.text == "Retried answer with healed session."
    assert resp.conversation_id == "conv_healed_fresh"
    assert mock_client.chat.call_count == 2
    # Second call had None for conversation_id
    assert mock_client.chat.call_args_list[1][1]["conversation_id"] is None

