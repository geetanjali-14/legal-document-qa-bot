import pytest
from pathlib import Path
import tempfile
from fastapi.testclient import TestClient
from app.main import app, app_state
from app.persistence.database import DatabaseManager
from app.persistence.repository import ConversationRepository
from app.services.conversation_service import ConversationService
from app.models.chat import Citation
from app.core.telemetry import ChatTelemetry


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_legal_qa.db"
        db_mgr = DatabaseManager(db_path=db_path)
        repo = ConversationRepository(session_factory=db_mgr.session_factory)
        service = ConversationService(repository=repo)
        yield {
            "db_path": db_path,
            "db_mgr": db_mgr,
            "repo": repo,
            "service": service
        }


# =====================================================================
# 1. Conversation Repository Unit Tests
# =====================================================================

def test_create_and_retrieve_conversation(temp_db):
    service: ConversationService = temp_db["service"]
    conv = service.create_conversation(
        document_id="doc_123",
        title="Test Vendor Agreement"
    )
    assert conv.conversation_id.startswith("conv_")
    assert conv.title == "Test Vendor Agreement"
    assert "doc_123" in conv.document_ids
    assert conv.status == "active"
    assert conv.created_at is not None
    assert conv.updated_at is not None

    fetched = service.get_conversation(conv.conversation_id)
    assert fetched is not None
    assert fetched.conversation_id == conv.conversation_id
    assert fetched.title == "Test Vendor Agreement"
    assert len(fetched.messages) == 0


def test_list_conversations_ordered(temp_db):
    service: ConversationService = temp_db["service"]
    c1 = service.create_conversation(title="First")
    c2 = service.create_conversation(title="Second")

    convs = service.list_conversations()
    assert len(convs) >= 2
    # Most recently updated first
    ids = [c.conversation_id for c in convs]
    assert ids.index(c2.conversation_id) < ids.index(c1.conversation_id)


def test_update_and_delete_conversation(temp_db):
    service: ConversationService = temp_db["service"]
    conv = service.create_conversation(document_id="doc_delete", title="Initial Title")
    updated = service.update_conversation(conv.conversation_id, title="Renamed Title", status="archived")
    assert updated.title == "Renamed Title"
    assert updated.status == "archived"

    deleted = service.delete_conversation(conv.conversation_id, "doc_delete")
    assert deleted is True
    assert service.get_conversation(conv.conversation_id) is None


# =====================================================================
# 2. Message Persistence & Ordering
# =====================================================================

def test_add_messages_sequence_and_history(temp_db):
    service: ConversationService = temp_db["service"]
    conv = service.create_conversation(document_id="doc_test")

    # Add user message
    m1 = service.add_message(
        conversation_id=conv.conversation_id,
        role="user",
        content="What is the termination period?"
    )
    assert m1.sequence == 1
    assert m1.role == "user"

    # Add assistant message with citations and telemetry
    citation = Citation(
        document_id="doc_test",
        document_name="contract.pdf",
        page_number=3,
        section="Termination",
        chunk_id="chk_1",
        snippet="Notice of 30 days is required.",
        relevance_score=0.85
    )
    telemetry = ChatTelemetry(
        request_id="req_test_123",
        timestamp=conv.created_at.isoformat(),
        document_id="doc_test",
        status="supported",
        total_latency_ms=120.5
    )

    m2 = service.add_message(
        conversation_id=conv.conversation_id,
        role="assistant",
        content="The notice period is 30 days.",
        intent="specific_fact",
        evidence_state="supported",
        sources=[citation],
        telemetry=telemetry
    )
    assert m2.sequence == 2
    assert m2.role == "assistant"
    assert len(m2.sources) == 1
    assert m2.sources[0].page_number == 3
    assert m2.telemetry.total_latency_ms == 120.5

    # Retrieve full conversation
    detail = service.get_conversation(conv.conversation_id)
    assert len(detail.messages) == 2
    assert detail.messages[0].sequence == 1
    assert detail.messages[1].sequence == 2
    assert detail.messages[1].content == "The notice period is 30 days."


def test_conversation_persistence_across_manager_restarts(temp_db):
    db_path = temp_db["db_path"]
    service: ConversationService = temp_db["service"]
    conv = service.create_conversation(title="Durable Thread")
    service.add_message(conv.conversation_id, role="user", content="Hello persistence!")

    # Simulate application restart with new manager instance on same db_path
    new_db_mgr = DatabaseManager(db_path=db_path)
    new_repo = ConversationRepository(session_factory=new_db_mgr.session_factory)
    new_service = ConversationService(repository=new_repo)

    recovered = new_service.get_conversation(conv.conversation_id)
    assert recovered is not None
    assert recovered.title == "Durable Thread"
    assert len(recovered.messages) == 1
    assert recovered.messages[0].content == "Hello persistence!"


# =====================================================================
# 3. Chat API Integration & Backward Compatibility
# =====================================================================

def test_chat_flow_auto_creates_and_returns_conversation(monkeypatch, temp_db):
    monkeypatch.setitem(app_state, "conversation_service", temp_db["service"])

    with TestClient(app) as client:
        # 1. Use real synthetic contract
        pdf_path = Path("documents/synthetic_contract.pdf")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        doc_service = app_state["document_service"]
        meta = doc_service.process_document(pdf_bytes, "test_contract_persist.pdf")

        # 2. Chat request without conversation_id
        res = client.post(
            "/api/chat",
            json={
                "document_id": meta.document_id,
                "question": "What is the termination notice period?"
            }
        )
        assert res.status_code == 200
        data = res.json()["data"]
        conv_id = data.get("conversation_id")
        assert conv_id is not None
        assert conv_id.startswith("conv_")

        # 3. Verify conversation was persisted with 2 messages (user + assistant)
        service: ConversationService = temp_db["service"]
        conv_detail = service.get_conversation(conv_id)
        assert conv_detail is not None
        assert len(conv_detail.messages) == 2
        assert conv_detail.messages[0].role == "user"
        assert conv_detail.messages[0].content == "What is the termination notice period?"
        assert conv_detail.messages[1].role == "assistant"

        # 4. Subsequent request with the same conversation_id
        res2 = client.post(
            "/api/chat",
            json={
                "document_id": meta.document_id,
                "conversation_id": conv_id,
                "question": "Where must dispute arbitration take place?"
            }
        )
        assert res2.status_code == 200
        data2 = res2.json()["data"]
        assert data2.get("conversation_id") == conv_id

        # 5. Verify conversation now has 4 ordered messages
        conv_detail2 = service.get_conversation(conv_id)
        assert len(conv_detail2.messages) == 4
        assert [m.sequence for m in conv_detail2.messages] == [1, 2, 3, 4]


def test_chat_invalid_conversation_id_returns_404(monkeypatch, temp_db):
    monkeypatch.setitem(app_state, "conversation_service", temp_db["service"])

    with TestClient(app) as client:
        pdf_path = Path("documents/synthetic_contract.pdf")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        doc_service = app_state["document_service"]
        meta = doc_service.process_document(pdf_bytes, "test_contract_persist2.pdf")

        res = client.post(
            "/api/chat",
            json={
                "document_id": meta.document_id,
                "conversation_id": "conv_nonexistent_9999",
                "question": "Is this found?"
            }
        )
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


# =====================================================================
# 4. Conversation Endpoints REST Tests
# =====================================================================

def test_conversations_rest_endpoints(monkeypatch, temp_db):
    monkeypatch.setitem(app_state, "conversation_service", temp_db["service"])

    with TestClient(app) as client:
        # POST /api/conversations
        res = client.post(
            "/api/conversations",
            json={"title": "Master Services Agreement Review", "document_id": "doc_abc"}
        )
        assert res.status_code == 201
        conv_data = res.json()["data"]
        c_id = conv_data["conversation_id"]
        assert conv_data["title"] == "Master Services Agreement Review"

        # GET /api/conversations
        res_list = client.get("/api/conversations")
        assert res_list.status_code == 200
        assert len(res_list.json()["data"]) >= 1

        # GET /api/conversations/{id}
        res_get = client.get(f"/api/conversations/{c_id}")
        assert res_get.status_code == 200
        assert res_get.json()["data"]["conversation_id"] == c_id

        # PATCH /api/conversations/{id}
        res_patch = client.patch(
            f"/api/conversations/{c_id}",
            json={"title": "Updated Title"}
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["data"]["title"] == "Updated Title"

        # A different document scope cannot delete this conversation.
        res_wrong_scope = client.delete(f"/api/conversations/{c_id}?document_id=doc_other")
        assert res_wrong_scope.status_code == 404
        assert client.get(f"/api/conversations/{c_id}").status_code == 200

        # DELETE /api/conversations/{id} within the associated document scope
        res_del = client.delete(f"/api/conversations/{c_id}?document_id=doc_abc")
        assert res_del.status_code == 200
        assert res_del.json()["data"]["deleted"] is True

        # Confirm 404 after deletion
        res_after = client.get(f"/api/conversations/{c_id}")
        assert res_after.status_code == 404


def test_conversation_delete_requires_associated_document_scope(temp_db):
    service: ConversationService = temp_db["service"]
    conv = service.create_conversation(document_id="doc_owner")
    service.add_message(conv.conversation_id, role="user", content="Keep this isolated")

    assert service.delete_conversation(conv.conversation_id, "doc_other") is False
    assert service.get_conversation(conv.conversation_id) is not None
    assert service.delete_conversation(conv.conversation_id, "doc_owner") is True
    assert service.get_conversation(conv.conversation_id) is None


def test_delete_all_conversations(temp_db):
    service: ConversationService = temp_db["service"]
    c1 = service.create_conversation(document_id="doc_1")
    c2 = service.create_conversation(document_id="doc_2")
    service.add_message(c1.conversation_id, role="user", content="msg 1")
    service.add_message(c2.conversation_id, role="user", content="msg 2")

    assert len(service.list_conversations()) == 2
    deleted = service.delete_all_conversations()
    assert deleted == 2
    assert len(service.list_conversations()) == 0


def test_delete_all_conversations_api(monkeypatch, temp_db):
    monkeypatch.setitem(app_state, "conversation_service", temp_db["service"])
    service: ConversationService = temp_db["service"]
    c1 = service.create_conversation(document_id="doc_1")
    service.add_message(c1.conversation_id, role="user", content="msg 1")

    with TestClient(app) as client:
        res = client.delete("/api/conversations")
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["data"]["deleted_count"] >= 1


# =====================================================================
# 5. Automatic Conversation Title Generation Tests
# =====================================================================

def test_auto_conversation_title_generation(temp_db):
    service: ConversationService = temp_db["service"]

    # 1. Notice period question
    c1 = service.create_conversation(title="New Legal Consultation")
    service.add_message(
        conversation_id=c1.conversation_id,
        role="user",
        content="What is the notice period for early termination?"
    )
    detail1 = service.get_conversation(c1.conversation_id)
    assert detail1.title == "Early Termination Notice Period"

    # 2. Calculation question
    c2 = service.create_conversation(title="Consultation for doc_xyz")
    service.add_message(
        conversation_id=c2.conversation_id,
        role="user",
        content="How is the first annual increment calculated?"
    )
    detail2 = service.get_conversation(c2.conversation_id)
    assert detail2.title == "Annual Increment Calculation"

    # 3. Subsequent message does not overwrite existing title (title stability)
    service.add_message(
        conversation_id=c2.conversation_id,
        role="user",
        content="Can you also explain the severance package?"
    )
    detail2_after = service.get_conversation(c2.conversation_id)
    assert detail2_after.title == "Annual Increment Calculation"

    # 4. Custom non-generic title is preserved
    c3 = service.create_conversation(title="Custom Project Alpha Agreement")
    service.add_message(
        conversation_id=c3.conversation_id,
        role="user",
        content="What is the notice period for early termination?"
    )
    detail3 = service.get_conversation(c3.conversation_id)
    assert detail3.title == "Custom Project Alpha Agreement"


