import pytest
from app.services.conversation_service import ConversationService
from app.persistence.database import DatabaseManager
from app.persistence.repository import ConversationRepository
from app.models.chat import Citation
from app.core.telemetry import ChatTelemetry, estimate_tokens


@pytest.fixture
def test_conv_service(tmp_path):
    db_file = tmp_path / "test_context.db"
    db_manager = DatabaseManager(db_file)
    repo = ConversationRepository(db_manager.session_factory)
    return ConversationService(repo)


def test_ensure_conversation_exists_document_association(test_conv_service):
    # Auto-create conversation with doc1
    conv = test_conv_service.ensure_conversation_exists(
        conversation_id=None,
        document_id="doc_100"
    )
    assert conv.conversation_id is not None
    assert "doc_100" in conv.document_ids

    # Calling again with existing conv_id and doc2 attaches doc2
    updated = test_conv_service.ensure_conversation_exists(
        conversation_id=conv.conversation_id,
        document_id="doc_200"
    )
    assert updated.conversation_id == conv.conversation_id
    assert "doc_100" in updated.document_ids
    assert "doc_200" in updated.document_ids

    # Calling with nonexistent conversation_id raises ValueError
    with pytest.raises(ValueError, match="not found"):
        test_conv_service.ensure_conversation_exists(
            conversation_id="nonexistent-id",
            document_id="doc_100"
        )


def test_get_bounded_history_turns_limit(test_conv_service):
    conv = test_conv_service.create_conversation(document_id="doc_test")
    conv_id = conv.conversation_id

    # Add 5 full turns (10 messages)
    for i in range(1, 6):
        test_conv_service.add_message(
            conversation_id=conv_id,
            role="user",
            content=f"User question {i}"
        )
        test_conv_service.add_message(
            conversation_id=conv_id,
            role="assistant",
            content=f"Assistant answer {i}",
            sources=[Citation(
                document_id="doc_test",
                document_name="Test.pdf",
                page_number=i,
                chunk_id=f"chk_{i}",
                snippet=f"Snippet {i}"
            )],
            telemetry=ChatTelemetry(
                request_id=f"req_{i}",
                timestamp="2026-10-07T00:00:00Z",
                status="supported",
                total_latency_ms=12.5
            )
        )

    # Request bounded history with max_turns=3 (should return 6 messages: turns 3, 4, 5)
    history = test_conv_service.get_bounded_history(conv_id, max_turns=3, max_tokens=1000)
    assert len(history) == 6
    assert history[0].role == "user"
    assert history[0].content == "User question 3"
    assert history[1].role == "assistant"
    assert history[1].content == "Assistant answer 3"
    assert history[-1].role == "assistant"
    assert history[-1].content == "Assistant answer 5"


def test_get_bounded_history_token_limit(test_conv_service):
    conv = test_conv_service.create_conversation(document_id="doc_test")
    conv_id = conv.conversation_id

    # Add long messages
    long_text = "This is a detailed legal obligation clause explanation text that consumes tokens. " * 15
    for i in range(3):
        test_conv_service.add_message(
            conversation_id=conv_id,
            role="user",
            content=f"User query {i}: {long_text}"
        )
        test_conv_service.add_message(
            conversation_id=conv_id,
            role="assistant",
            content=f"Assistant reply {i}: {long_text}"
        )

    # Set token ceiling tight enough that not all 6 messages can fit
    tight_token_budget = 100
    bounded = test_conv_service.get_bounded_history(conv_id, max_turns=3, max_tokens=tight_token_budget)

    # Must be trimmed down to fit within tight_token_budget
    total_tokens = estimate_tokens("\n".join(f"{m.role}: {m.content}" for m in bounded))
    assert total_tokens <= tight_token_budget
    assert len(bounded) < 6


def test_get_bounded_history_empty_on_new_conversation(test_conv_service):
    conv = test_conv_service.create_conversation(document_id="doc_empty")
    history = test_conv_service.get_bounded_history(conv.conversation_id)
    assert history == []


# ==============================================================================
# PHASE 1 — CONVERSATION INTELLIGENCE REGRESSION & UNIT SUITE
# ==============================================================================
from unittest.mock import MagicMock
from app.models.chat import Message
from app.services.agent_orchestrator import AgentOrchestrator


@pytest.fixture
def mock_orchestrator():
    return AgentOrchestrator(
        intent_router=MagicMock(),
        metadata_tool=MagicMock(),
        profile_tool=MagicMock(),
        evidence_tool=MagicMock(),
        llm_service=MagicMock(),
        citation_service=MagicMock()
    )


def test_basic_two_turn_follow_up(mock_orchestrator):
    """
    Q1: What is the notice period for early termination?
    Q2: Who can initiate it? -> who can initiate early termination?
    """
    history = [
        Message(role="user", content="What is the notice period for early termination?"),
        Message(role="assistant", content="The agreement requires thirty (30) days notice.")
    ]
    resolved = mock_orchestrator._contextualize_query("Who can initiate it?", history)
    assert "early termination" in resolved.lower()
    assert "who can initiate" in resolved.lower()


def test_three_turn_regression_sequence(mock_orchestrator):
    """
    Exact required regression sequence:
    Q1: What is the notice period for early termination?
    Q2: Who can initiate it?
    Q3: What happens to indemnification obligations after that occurs?
    """
    h1 = [
        Message(role="user", content="What is the notice period for early termination?"),
        Message(role="assistant", content="The notice period is thirty (30) days.")
    ]
    resolved_q2 = mock_orchestrator._contextualize_query("Who can initiate it?", h1)
    assert "early termination" in resolved_q2.lower()

    h2 = h1 + [
        Message(role="user", content="Who can initiate it?"),
        Message(role="assistant", content="Either party may terminate the agreement early.")
    ]
    resolved_q3 = mock_orchestrator._contextualize_query(
        "What happens to indemnification obligations after that occurs?",
        h2
    )
    assert "indemnification" in resolved_q3.lower()
    assert "early termination" in resolved_q3.lower()


def test_pronouns_resolution(mock_orchestrator):
    """
    Test resolution of various pronouns: it, that, this, they, them, its.
    """
    history = [
        Message(role="user", content="What are the confidentiality obligations?"),
        Message(role="assistant", content="Proprietary information must be protected for 3 years.")
    ]

    # "them"
    r_them = mock_orchestrator._contextualize_query("Who is responsible for them?", history)
    assert "confidentiality" in r_them.lower()

    # "it"
    r_it = mock_orchestrator._contextualize_query("How long does it last?", history)
    assert "confidentiality" in r_it.lower()

    # "they"
    r_they = mock_orchestrator._contextualize_query("Can they assign them?", history)
    assert "confidentiality" in r_they.lower()

    # "its"
    r_its = mock_orchestrator._contextualize_query("What is its duration?", history)
    assert "confidentiality" in r_its.lower()


def test_legal_concepts_anaphora(mock_orchestrator):
    """
    Test legal concept references: the provision, the obligation, the termination, following that.
    """
    history = [
        Message(role="user", content="Review the governing law clause."),
        Message(role="assistant", content="This agreement is governed by the laws of California under Section 12.")
    ]
    r_prov = mock_orchestrator._contextualize_query("What remedies exist under the provision?", history)
    assert "governing law" in r_prov.lower()


def test_topic_switching(mock_orchestrator):
    """
    Topic changes from termination -> confidentiality -> follow-up on confidentiality.
    The system must resolve 'them' to confidentiality, NOT termination.
    """
    history = [
        Message(role="user", content="What is the termination notice period?"),
        Message(role="assistant", content="Termination requires 30 days written notice."),
        Message(role="user", content="What are the confidentiality obligations?"),
        Message(role="assistant", content="Parties shall keep confidential information protected for five years.")
    ]
    resolved = mock_orchestrator._contextualize_query("Who is responsible for them?", history)
    assert "confidentiality" in resolved.lower()
    assert "termination" not in resolved.lower()


def test_intermediate_turns_continuity(mock_orchestrator):
    """
    Q1: What is the termination notice period?
    Q2: Who can initiate it?
    Q3: What are their obligations?
    Should retain termination topic context.
    """
    history = [
        Message(role="user", content="What is the termination notice period?"),
        Message(role="assistant", content="30 days written notice."),
        Message(role="user", content="Who can initiate it?"),
        Message(role="assistant", content="Either party may initiate termination.")
    ]
    resolved = mock_orchestrator._contextualize_query("What are their obligations?", history)
    assert "termination" in resolved.lower()


def test_event_reference_resolution(mock_orchestrator):
    """
    Q1: What happens if the agreement is terminated?
    Q2: What happens after that? -> What happens after early termination?
    """
    history = [
        Message(role="user", content="What happens if the agreement is terminated?"),
        Message(role="assistant", content="The consultant must return all materials within 10 days.")
    ]
    resolved = mock_orchestrator._contextualize_query("What happens after that?", history)
    assert "after early termination" in resolved.lower() or "after termination" in resolved.lower()


def test_self_contained_questions_preserved(mock_orchestrator):
    """
    Self-contained questions must NOT be modified or have previous context appended.
    """
    history = [
        Message(role="user", content="What is the notice period for early termination?"),
        Message(role="assistant", content="30 days notice under Section 4.")
    ]

    # Specific clause question
    q_sec = "What is the liability cap under Section 8.2?"
    assert mock_orchestrator._contextualize_query(q_sec, history) == q_sec

    # Specific self-contained subject question
    q_conf = "What are the confidentiality obligations of the vendor?"
    assert mock_orchestrator._contextualize_query(q_conf, history) == q_conf


def test_long_conversation_preserves_state(mock_orchestrator):
    """
    Long multi-turn conversation maintains structured state correctly.
    """
    history = [
        Message(role="user", content="Tell me about the effective date."),
        Message(role="assistant", content="The effective date is January 1, 2024."),
        Message(role="user", content="What is the notice period for early termination?"),
        Message(role="assistant", content="30 days notice is required."),
        Message(role="user", content="Who can initiate it?"),
        Message(role="assistant", content="Either the Commission or Consultant may initiate it."),
        Message(role="user", content="Does that continue afterward?"),
        Message(role="assistant", content="Certain covenants survive termination.")
    ]
    state = mock_orchestrator.build_conversation_state("doc_test", history)
    assert state.active_topic == "early termination"
    assert "early termination" in state.active_events

