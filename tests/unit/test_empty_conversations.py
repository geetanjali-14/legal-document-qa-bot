import io
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.main import app, app_state
from app.services.conversation_service import ConversationService
from app.models.response import ApiResponse


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _create_simple_image(text: str) -> bytes:
    img = Image.new("RGB", (600, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestEmptyConversationsAndIsolation:
    """Requirements 17, 18, 19: Empty chat persistence prevention, document switching, and deletion safety."""

    def test_new_chat_or_opening_ui_does_not_persist_conversation(self, client: TestClient):
        """Merely requesting conversation list or opening app should have no empty chats created."""
        conv_service: ConversationService = app_state["conversation_service"]
        initial_count = len(conv_service.list_conversations(include_empty=True))

        # Check conversation endpoint
        resp = client.get("/api/conversations?include_empty=false")
        assert resp.status_code == 200
        # Check total database count hasn't grown
        assert len(conv_service.list_conversations(include_empty=True)) == initial_count

    def test_blank_or_whitespace_messages_rejected_and_not_persisted(self, client: TestClient):
        """Empty string, whitespace only, newlines are rejected and persist 0 conversations."""
        conv_service: ConversationService = app_state["conversation_service"]
        before_count = len(conv_service.list_conversations(include_empty=True))

        for invalid_question in ["", "   ", "\n", "\t \n "]:
            resp = client.post(
                "/api/chat",
                json={
                    "document_id": "doc_arbitrary",
                    "question": invalid_question
                }
            )
            # Pydantic validation rejects with 422
            assert resp.status_code == 422

        after_count = len(conv_service.list_conversations(include_empty=True))
        assert after_count == before_count

    def test_first_valid_message_creates_exactly_one_persisted_conversation(self, client: TestClient):
        """First valid question persists exactly 1 conversation containing the user message."""
        # 1. Upload a test image document
        img_bytes = _create_simple_image("ARTICLE 1: CONFIDENTIALITY OBLIGATIONS.\nDisclosing party shall mark confidential.")
        upload_resp = client.post(
            "/api/documents/upload",
            files={"file": ("single_conv_test.png", img_bytes, "image/png")}
        )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["data"]["document_id"]

        # 2. Chat with no conversation_id provided (first user message)
        chat_resp = client.post(
            "/api/chat",
            json={
                "document_id": doc_id,
                "question": "What does Article 1 require?"
            }
        )
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()["data"]
        conv_id = chat_data["conversation_id"]
        assert conv_id is not None
        assert conv_id.startswith("conv_")

        # 3. Verify conversation is persisted and listed in sidebar (include_empty=False)
        list_resp = client.get("/api/conversations?include_empty=false")
        assert list_resp.status_code == 200
        active_convs = [c for c in list_resp.json()["data"] if c["conversation_id"] == conv_id]
        assert len(active_convs) == 1
        assert active_convs[0]["message_count"] >= 2  # user + assistant

    def test_failed_first_request_does_not_leave_orphaned_conversation(self, client: TestClient, monkeypatch):
        """If processing fails on the first question, rollback_if_failed cleans up the empty conversation."""
        from app.services.agent_orchestrator import AgentOrchestrator
        conv_service: ConversationService = app_state["conversation_service"]

        # 1. Upload a valid document first so validation passes
        img_bytes = _create_simple_image("SECTION 4: INDEMNIFICATION.\nParty A agrees to indemnify Party B.")
        upload_resp = client.post(
            "/api/documents/upload",
            files={"file": ("indemnity_doc.png", img_bytes, "image/png")}
        )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["data"]["document_id"]

        def mock_failing_process(*args, **kwargs):
            raise RuntimeError("Simulated internal LLM service outage during first interaction")

        monkeypatch.setattr(AgentOrchestrator, "process_query", mock_failing_process)

        # Attempt chat
        resp = client.post(
            "/api/chat",
            json={
                "document_id": doc_id,
                "question": "Will this fail gracefully?"
            }
        )
        assert resp.status_code == 500

        # Verify no empty conversation was left behind
        empty_count = conv_service.cleanup_empty_conversations()
        assert empty_count == 0  # Was already cleaned up or never committed

    def test_deleting_conversation_does_not_delete_document(self, client: TestClient):
        """Requirement 18: Deleting a conversation permanently removes messages and thread, leaving doc intact."""
        img_bytes = _create_simple_image("SECTION 9: SEVERABILITY.\nIf any provision is held invalid the remainder holds.")
        upload_resp = client.post(
            "/api/documents/upload",
            files={"file": ("severability_doc.png", img_bytes, "image/png")}
        )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["data"]["document_id"]

        # Create conversation by asking question
        chat_resp = client.post(
            "/api/chat",
            json={
                "document_id": doc_id,
                "question": "What is the severability clause?"
            }
        )
        assert chat_resp.status_code == 200
        conv_id = chat_resp.json()["data"]["conversation_id"]

        # Delete conversation
        del_resp = client.delete(f"/api/conversations/{conv_id}?document_id={doc_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["data"]["deleted"] is True

        # Check conversation is gone
        get_conv_resp = client.get(f"/api/conversations/{conv_id}")
        assert get_conv_resp.status_code == 404

        # Check document still exists and can be retrieved
        doc_resp = client.get(f"/api/documents/{doc_id}")
        assert doc_resp.status_code == 200
        assert doc_resp.json()["data"]["document_id"] == doc_id

    def test_combined_document_and_conversation_switching_behavior(self, client: TestClient):
        """
        Requirement 18 & 19 Combined:
        Document A
          -> create/use Conversation A
          -> New Chat
          -> switch to Document B
          -> verify no empty conversation was persisted
          -> ask question
          -> verify Conversation B belongs to Document B
          -> switch back to A
          -> verify A's conversation remains isolated
        """
        # Upload Document A
        bytes_a = _create_simple_image("DOCUMENT A: GOVERNING LAW.\nThis agreement is governed by Delaware law.")
        resp_a = client.post("/api/documents/upload", files={"file": ("doc_a.png", bytes_a, "image/png")})
        doc_a_id = resp_a.json()["data"]["document_id"]

        # Upload Document B
        bytes_b = _create_simple_image("DOCUMENT B: GOVERNING LAW.\nThis agreement is governed by California law.")
        resp_b = client.post("/api/documents/upload", files={"file": ("doc_b.png", bytes_b, "image/png")})
        doc_b_id = resp_b.json()["data"]["document_id"]

        # 1. Ask question on Document A -> Conversation A created
        chat_a = client.post("/api/chat", json={"document_id": doc_a_id, "question": "What is the governing law in Document A?"})
        assert chat_a.status_code == 200
        conv_a_id = chat_a.json()["data"]["conversation_id"]
        assert "delaware" in chat_a.json()["data"]["answer"].lower()

        # 2. Simulate User clicking 'New Chat' and selecting Document B (pure frontend action)
        # Verify no empty conversation was persisted in DB
        conv_service: ConversationService = app_state["conversation_service"]
        empty_cleaned = conv_service.cleanup_empty_conversations()
        assert empty_cleaned == 0

        # 3. Ask question on Document B -> Conversation B created
        chat_b = client.post("/api/chat", json={"document_id": doc_b_id, "question": "What is the governing law in Document B?"})
        assert chat_b.status_code == 200
        conv_b_id = chat_b.json()["data"]["conversation_id"]
        assert "california" in chat_b.json()["data"]["answer"].lower()
        assert conv_b_id != conv_a_id

        # 4. Verify Conversation B belongs to Document B
        conv_b_detail = client.get(f"/api/conversations/{conv_b_id}").json()["data"]
        assert doc_b_id in conv_b_detail["document_ids"]
        assert doc_a_id not in conv_b_detail["document_ids"]

        # 5. Verify Conversation A remains isolated to Document A
        conv_a_detail = client.get(f"/api/conversations/{conv_a_id}").json()["data"]
        assert doc_a_id in conv_a_detail["document_ids"]
        assert doc_b_id not in conv_a_detail["document_ids"]
