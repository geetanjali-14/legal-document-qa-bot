import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_v1_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "rag_provider" in data
    assert "llm_provider" in data


def test_v1_documents_crud_and_chat(client):
    # 1. Health & initial empty or existing documents
    res_list = client.get("/api/v1/documents")
    assert res_list.status_code == 200
    assert "documents" in res_list.json()

    # 2. Upload a genuine legal contract document
    pdf_path = Path("documents/rental_agreement.pdf")
    if not pdf_path.exists():
        pytest.skip("rental_agreement.pdf not found")

    with open(pdf_path, "rb") as f:
        file_content = f.read()

    files = {"file": ("rental_agreement.pdf", io.BytesIO(file_content), "application/pdf")}
    upload_res = client.post("/api/v1/documents", files=files)
    assert upload_res.status_code in (201, 200)
    upload_data = upload_res.json()
    doc_id = upload_data["document_id"]
    assert doc_id.startswith("doc_")

    try:
        # 3. Get document details
        detail_res = client.get(f"/api/v1/documents/{doc_id}")
        assert detail_res.status_code == 200
        assert detail_res.json()["document_id"] == doc_id

        # 4. Chat with document
        chat_res = client.post("/api/v1/chat", json={
            "document_id": doc_id,
            "question": "What is the termination notice period?"
        })
        assert chat_res.status_code == 200
        chat_data = chat_res.json()
        assert "answer" in chat_data
        assert "conversation_id" in chat_data
        assert isinstance(chat_data["sources"], list)

        # 5. Conversations
        conv_id = chat_data["conversation_id"]
        conv_res = client.get(f"/api/v1/conversations/{conv_id}")
        assert conv_res.status_code == 200
        assert conv_res.json()["id"] == conv_id

    finally:
        # 6. Cleanup: Delete document
        del_res = client.delete(f"/api/v1/documents/{doc_id}")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

        # Verify not found after deletion
        get_deleted = client.get(f"/api/v1/documents/{doc_id}")
        assert get_deleted.status_code == 404
        assert get_deleted.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_v1_error_handling(client):
    # Non-existent document
    res = client.get("/api/v1/documents/non_existent_doc_123")
    assert res.status_code == 404
    body = res.json()
    assert "error" in body
    assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"

    # Empty query rejection
    chat_res = client.post("/api/v1/chat", json={
        "question": ""
    })
    assert chat_res.status_code in (400, 422)
