import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["status"] == "healthy"


def test_reject_invalid_file_extension(client):
    files = {"file": ("malicious.exe", b"executable bytes", "application/octet-stream")}
    response = client.post("/api/documents/upload", files=files)
    assert response.status_code == 400
    assert "Only PDF documents are accepted" in response.json()["detail"]


def test_reject_non_pdf_content(client):
    files = {"file": ("fake.pdf", b"This is not a real PDF file header", "application/pdf")}
    response = client.post("/api/documents/upload", files=files)
    assert response.status_code == 400
    assert "Invalid file format" in response.json()["detail"]


def test_end_to_end_legal_rag_flow(client):
    pdf_path = Path("documents/synthetic_contract.pdf")
    assert pdf_path.exists(), "Synthetic test contract must exist."

    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("synthetic_contract.pdf", f, "application/pdf")}
        )

    assert response.status_code == 201
    upload_data = response.json()["data"]
    doc_id = upload_data["document_id"]
    assert upload_data["page_count"] == 3
    assert upload_data["chunk_count"] > 0

    # 1. Ask known question (Termination notice period)
    chat_resp = client.post(
        "/api/chat",
        json={
            "document_id": doc_id,
            "question": "What is the termination notice period?"
        }
    )
    assert chat_resp.status_code == 200
    res_data = chat_resp.json()["data"]
    assert "30 days" in res_data["answer"]
    assert len(res_data["sources"]) > 0
    assert res_data["sources"][0]["page_number"] == 1
    assert "Termination" in res_data["sources"][0]["section"]

    # 2. Ask known question about governing law
    chat_resp_law = client.post(
        "/api/chat",
        json={
            "document_id": doc_id,
            "question": "Which state's governing law applies to this contract?"
        }
    )
    assert chat_resp_law.status_code == 200
    res_law_data = chat_resp_law.json()["data"]
    assert "Delaware" in res_law_data["answer"]
    assert res_law_data["sources"][0]["page_number"] == 3

    # 3. Negative test: Ask completely unrelated question not in contract
    chat_resp_unrelated = client.post(
        "/api/chat",
        json={
            "document_id": doc_id,
            "question": "What is the protocol for launching a SpaceX rocket to Mars?"
        }
    )
    assert chat_resp_unrelated.status_code == 200
    res_unrelated_data = chat_resp_unrelated.json()["data"]
    assert "couldn't find enough information" in res_unrelated_data["answer"].lower()
    assert res_unrelated_data["confidence"] == "insufficient_context"
    assert len(res_unrelated_data["sources"]) == 0

    # 4. Clean up / Delete document
    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 200
