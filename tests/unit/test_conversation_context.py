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
