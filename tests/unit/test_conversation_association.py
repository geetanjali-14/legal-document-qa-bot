import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.services.conversation_service import ConversationService
from app.persistence.database import DatabaseManager
from app.persistence.repository import ConversationRepository


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def conv_service(tmp_path):
    db_file = tmp_path / "test_assoc.db"
    db_manager = DatabaseManager(db_file)
    repo = ConversationRepository(db_manager.session_factory)
    return ConversationService(repo)


import io
from PIL import Image, ImageDraw

def _create_test_image(text: str) -> bytes:
    img = Image.new("RGB", (800, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestConversationDocumentAssociationInvariant:
    """
    Focused tests for conversation/document association:
    1. No conversation_id + document_id -> creates new conversation for document.
    2. Existing conversation + same document -> reuses conversation.
    3. Existing conversation + unrelated document -> rejected / not reused.
    4. Existing conversation + document legitimately associated with it -> reuses conversation.
    5. Re-uploaded/re-ingested logical document with new document_id -> old conv not reused.
    6. Missing conversation_id -> raises 404 / error consistently.
    """

    def test_no_conversation_id_creates_new_conversation(self, conv_service):
        conv = conv_service.ensure_conversation_exists(
            conversation_id=None,
            document_id="doc_alpha"
        )
        assert conv.conversation_id is not None
        assert conv.document_ids == ["doc_alpha"]

    def test_existing_conversation_same_document_reuses(self, conv_service):
        c1 = conv_service.ensure_conversation_exists(
            conversation_id=None,
            document_id="doc_alpha"
        )
        c2 = conv_service.ensure_conversation_exists(
            conversation_id=c1.conversation_id,
            document_id="doc_alpha"
        )
        assert c2.conversation_id == c1.conversation_id
        assert c2.document_ids == ["doc_alpha"]

    def test_existing_conversation_unrelated_document_rejected(self, client: TestClient):
        # Create conversation for doc_alpha
        img_a = _create_test_image("ARTICLE 1: CONFIDENTIALITY OBLIGATIONS.\nThe disclosing party shall mark confidential information accordingly.")
        up_a = client.post("/api/documents/upload", files={"file": ("doc_a.png", img_a, "image/png")})
        doc_a_id = up_a.json()["data"]["document_id"]

        chat_resp = client.post("/api/chat", json={
            "document_id": doc_a_id,
            "question": "What is the confidentiality rule?"
        })
        conv_id = chat_resp.json()["data"]["conversation_id"]

        # Upload a second document
        img_b = _create_test_image("ARTICLE 2: TERMINATION CLAUSE AND NOTICE.\nTermination requires thirty days written notice prior to end.")
        up_b = client.post("/api/documents/upload", files={"file": ("doc_b.png", img_b, "image/png")})
        doc_b_id = up_b.json()["data"]["document_id"]

        # Request with same conv_id but unrelated doc_b_id
        mismatch_resp = client.post("/api/chat", json={
            "document_id": doc_b_id,
            "conversation_id": conv_id,
            "question": "What is the termination clause?"
        })
        assert mismatch_resp.status_code == 400
        assert "does not belong to document" in mismatch_resp.json()["detail"]
        assert "maintain document isolation" in mismatch_resp.json()["detail"]

    def test_existing_conversation_legitimately_associated_multidoc_reuses(self, conv_service):
        # Create conversation with doc_alpha and doc_beta
        conv = conv_service.create_conversation(
            document_ids=["doc_alpha", "doc_beta"],
            title="Comparison Consultation"
        )
        c_reuse = conv_service.ensure_conversation_exists(
            conversation_id=conv.conversation_id,
            document_id="doc_beta"
        )
        assert c_reuse.conversation_id == conv.conversation_id
        assert "doc_alpha" in c_reuse.document_ids
        assert "doc_beta" in c_reuse.document_ids

    def test_reuploaded_document_new_id_old_conv_not_reused(self, client: TestClient):
        # Upload doc 1
        img1 = _create_test_image("DOC 1: TERM OF AGREEMENT.\nInitial term is 12 months.")
        up1 = client.post("/api/documents/upload", files={"file": ("doc_1.png", img1, "image/png")})
        doc1_id = up1.json()["data"]["document_id"]

        chat1 = client.post("/api/chat", json={
            "document_id": doc1_id,
            "question": "What is the contract term?"
        })
        conv1_id = chat1.json()["data"]["conversation_id"]

        # Upload a second distinct document to represent newly ingested document ID
        img2 = _create_test_image("DOC 2: TERM OF AGREEMENT.\nInitial term is 24 months.")
        up2 = client.post("/api/documents/upload", files={"file": ("doc_2.png", img2, "image/png")})
        new_doc_id = up2.json()["data"]["document_id"]

        res = client.post("/api/chat", json={
            "document_id": new_doc_id,
            "conversation_id": conv1_id,
            "question": "What is the contract term?"
        })
        assert res.status_code == 400
        assert "does not belong to document" in res.json()["detail"]

    def test_missing_conversation_id_returns_404(self, client: TestClient):
        res = client.post("/api/chat", json={
            "document_id": "doc_test_123",
            "conversation_id": "conv_does_not_exist_999",
            "question": "What is clause 1?"
        })
        assert res.status_code == 404
        assert "was not found" in res.json()["detail"]
