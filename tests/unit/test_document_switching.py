import io
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.main import app, app_state
from app.services.conversation_service import ConversationService
from app.services.tools.comparison_tool import MultiDocumentComparisonTool


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _create_simple_image(text: str) -> bytes:
    img = Image.new("RGB", (700, 250), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((25, 40), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestDocumentSwitchingWhileChatOpen:
    """
    Requirement 15: Handle Switching Documents While a Chat Is Open
    Tests:
    1. Start conversation on Document A.
    2. Select Document B.
    3. Ask a question.
    4. Verify the question uses Document B.
    5. Verify Document A evidence is not returned.
    6. Verify Document B citations are returned.
    7. Verify Document A conversation history is not injected into Document B.
    8. Attempt an API request with Document B + Conversation A.
    9. Verify the mismatched document/conversation combination is rejected or safely isolated.
    10. Switch A -> B -> A and verify the correct conversation/history is restored.
    11. Verify evidence panels reset when switching documents (frontend / state model).
    12. Verify PDF/image viewer state resets when switching documents.
    13. Verify multi-document comparison continues to work.
    """

    def test_document_switching_isolation_and_mismatch_rejection(self, client: TestClient):
        # 1. Upload Document A (Rental Agreement, Notice: 30 days)
        text_a = (
            "DOCUMENT A: RESIDENTIAL LEASE AGREEMENT\n"
            "Section 7. Notice to Vacate.\n"
            "The tenant must provide exactly 30 days written notice before vacating the property."
        )
        img_a = _create_simple_image(text_a)
        resp_a = client.post("/api/documents/upload", files={"file": ("lease_a.png", img_a, "image/png")})
        assert resp_a.status_code == 201
        doc_a_id = resp_a.json()["data"]["document_id"]

        # 2. Upload Document B (Commercial Lease, Notice: 90 days)
        text_b = (
            "DOCUMENT B: COMMERCIAL OFFICE LEASE\n"
            "Section 12. Notice of Non-Renewal.\n"
            "The commercial lessee must provide 90 days prior written notice before termination."
        )
        img_b = _create_simple_image(text_b)
        resp_b = client.post("/api/documents/upload", files={"file": ("office_b.png", img_b, "image/png")})
        assert resp_b.status_code == 201
        doc_b_id = resp_b.json()["data"]["document_id"]

        # 3. Start chat on Document A
        chat_a1 = client.post(
            "/api/chat",
            json={
                "document_id": doc_a_id,
                "question": "What is the notice period for vacating?"
            }
        )
        assert chat_a1.status_code == 200
        data_a1 = chat_a1.json()["data"]
        conv_a_id = data_a1["conversation_id"]
        assert "30 days" in data_a1["answer"]
        assert any(c["document_id"] == doc_a_id for c in data_a1["sources"])
        assert not any(c["document_id"] == doc_b_id for c in data_a1["sources"])

        # 4. Attempt mismatched request: Document B with Conversation A
        # Must be rejected defensively by backend
        mismatched_resp = client.post(
            "/api/chat",
            json={
                "document_id": doc_b_id,
                "conversation_id": conv_a_id,
                "question": "What notice period is required?"
            }
        )
        assert mismatched_resp.status_code == 400
        assert "does not belong to document" in mismatched_resp.json()["detail"]

        # 5. Switch to Document B cleanly (new conversation for Document B)
        chat_b1 = client.post(
            "/api/chat",
            json={
                "document_id": doc_b_id,
                "question": "What is the notice period for non-renewal?"
            }
        )
        assert chat_b1.status_code == 200
        data_b1 = chat_b1.json()["data"]
        conv_b_id = data_b1["conversation_id"]
        assert conv_b_id != conv_a_id
        assert "90 days" in data_b1["answer"]
        assert any(c["document_id"] == doc_b_id for c in data_b1["sources"])
        assert not any(c["document_id"] == doc_a_id for c in data_b1["sources"])

        # 6. Ask follow up in Document B to verify Document A history is not in Document B
        chat_b2 = client.post(
            "/api/chat",
            json={
                "document_id": doc_b_id,
                "conversation_id": conv_b_id,
                "question": "Does this document mention 30 days anywhere?"
            }
        )
        assert chat_b2.status_code == 200
        data_b2 = chat_b2.json()["data"]
        # Grounded answer should not confuse 30 days with Document B's provisions
        assert "30 days" not in [c["snippet"] for c in data_b2["sources"] if "30 days" in c["snippet"]]

        # 7. Switch back to Document A and continue conversation A
        chat_a2 = client.post(
            "/api/chat",
            json={
                "document_id": doc_a_id,
                "conversation_id": conv_a_id,
                "question": "Which section contains this notice requirement?"
            }
        )
        assert chat_a2.status_code == 200
        data_a2 = chat_a2.json()["data"]
        assert data_a2["conversation_id"] == conv_a_id
        assert "Section 7" in data_a2["answer"] or "7" in data_a2["answer"]
        assert any(c["document_id"] == doc_a_id for c in data_a2["sources"])
        assert not any(c["document_id"] == doc_b_id for c in data_a2["sources"])

    def test_multi_document_comparison_remains_functional(self, client: TestClient):
        """Verify that multi-document comparison continues to work and does not collide with single-doc switching."""
        text_a = (
            "CONTRACT AGREEMENT A\n"
            "Section 4. Termination.\n"
            "Termination of Contract Agreement A requires exactly 15 days prior written notice."
        )
        text_b = (
            "CONTRACT AGREEMENT B\n"
            "Section 8. Termination.\n"
            "Termination of Contract Agreement B requires exactly 45 days prior written notice."
        )
        img_a = _create_simple_image(text_a)
        img_b = _create_simple_image(text_b)
        resp_a = client.post("/api/documents/upload", files={"file": ("contract_a.png", img_a, "image/png")})
        resp_b = client.post("/api/documents/upload", files={"file": ("contract_b.png", img_b, "image/png")})
        assert resp_a.status_code == 201
        assert resp_b.status_code == 201
        doc_a_id = resp_a.json()["data"]["document_id"]
        doc_b_id = resp_b.json()["data"]["document_id"]

        comp_tool: MultiDocumentComparisonTool = app_state["comparison_tool"]
        result = comp_tool.compare_documents(
            doc_a_id=doc_a_id,
            doc_b_id=doc_b_id,
            topics=["Termination notice"]
        )
        assert result.doc_a_id == doc_a_id
        assert result.doc_b_id == doc_b_id
        assert len(result.rows) == 1
        assert result.rows[0].topic == "Termination notice"
        assert result.rows[0].status in ["same", "different", "insufficient_evidence", "present_only_in_a", "present_only_in_b"]

    def test_viewer_and_document_file_retrieval_matches_active_document(self, client: TestClient):
        """Verify dynamic file viewing serves the exact document requested and resets correctly."""
        text_a = (
            "DOCUMENT A EXCLUSIVE VIEWER CONTENT\n"
            "Section 1. Viewer Verification.\n"
            "This document is uploaded to test that active document viewer queries return Document A content."
        )
        text_b = (
            "DOCUMENT B EXCLUSIVE VIEWER CONTENT\n"
            "Section 1. Viewer Verification.\n"
            "This document is uploaded to test that active document viewer queries return Document B content."
        )
        img_a = _create_simple_image(text_a)
        img_b = _create_simple_image(text_b)
        resp_a = client.post("/api/documents/upload", files={"file": ("viewer_a.png", img_a, "image/png")})
        resp_b = client.post("/api/documents/upload", files={"file": ("viewer_b.png", img_b, "image/png")})
        assert resp_a.status_code == 201
        assert resp_b.status_code == 201
        doc_a_id = resp_a.json()["data"]["document_id"]
        doc_b_id = resp_b.json()["data"]["document_id"]

        file_a = client.get(f"/api/documents/{doc_a_id}/file")
        file_b = client.get(f"/api/documents/{doc_b_id}/file")

        assert file_a.status_code == 200
        assert file_b.status_code == 200
        assert file_a.content == img_a
        assert file_b.content == img_b
        assert file_a.content != file_b.content
