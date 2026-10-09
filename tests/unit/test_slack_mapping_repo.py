import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.persistence.database import Base
from app.integrations.slack_mapping_repo import SlackMappingRepository


@pytest.fixture
def in_memory_repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return SlackMappingRepository(session_factory=session_factory)


def test_user_and_thread_isolation(in_memory_repo):
    channel = "C12345"
    user_a = "U_ALICE"
    user_b = "U_BOB"
    thread_1 = "1678900000.000100"

    # Alice sets doc_1 in thread_1
    in_memory_repo.save_mapping(
        channel_id=channel,
        user_id=user_a,
        thread_ts=thread_1,
        document_id="doc_alice_lease",
        conversation_id="conv_alice_1"
    )

    # Bob asks in the same thread: Bob should NOT inherit Alice's context
    bob_mapping = in_memory_repo.get_mapping(
        channel_id=channel,
        user_id=user_b,
        thread_ts=thread_1
    )
    assert bob_mapping is None

    # Bob sets his own document in the same thread
    in_memory_repo.save_mapping(
        channel_id=channel,
        user_id=user_b,
        thread_ts=thread_1,
        document_id="doc_bob_nda",
        conversation_id="conv_bob_1"
    )

    # Verify Alice's context is untouched
    alice_mapping = in_memory_repo.get_mapping(
        channel_id=channel,
        user_id=user_a,
        thread_ts=thread_1
    )
    assert alice_mapping.document_id == "doc_alice_lease"
    assert alice_mapping.conversation_id == "conv_alice_1"

    # Verify Bob has his separate context
    bob_updated = in_memory_repo.get_mapping(
        channel_id=channel,
        user_id=user_b,
        thread_ts=thread_1
    )
    assert bob_updated.document_id == "doc_bob_nda"
    assert bob_updated.conversation_id == "conv_bob_1"


def test_clear_mapping(in_memory_repo):
    channel = "C12345"
    user = "U_CHARLIE"
    thread = "1678900000.000200"

    in_memory_repo.save_mapping(
        channel_id=channel,
        user_id=user,
        thread_ts=thread,
        document_id="doc_charlie",
        conversation_id="conv_charlie"
    )

    assert in_memory_repo.get_mapping(channel, user, thread_ts=thread) is not None

    cleared = in_memory_repo.clear_mapping(channel, user, thread_ts=thread)
    assert cleared is True

    assert in_memory_repo.get_mapping(channel, user, thread_ts=thread) is None


def test_team_id_fallback_resilience(in_memory_repo):
    """
    Verifies that if a document is saved without an explicit team_id (or with default_team),
    and a subsequent message event carries the explicit team_id "T12345",
    the repository gracefully retrieves the active document context.
    """
    channel = "D_DM_CHANNEL"
    user = "U_EMPLOYEE"

    # Saved with None team_id (resolves to default_team)
    in_memory_repo.save_mapping(
        channel_id=channel,
        user_id=user,
        team_id=None,
        thread_ts=None,
        document_id="doc_annual_increment",
        conversation_id=None
    )

    # Retrieved with explicit workspace team_id
    mapping = in_memory_repo.get_mapping(
        channel_id=channel,
        user_id=user,
        team_id="T0C7THV2CJF",
        thread_ts=None
    )
    assert mapping is not None
    assert mapping.document_id == "doc_annual_increment"


