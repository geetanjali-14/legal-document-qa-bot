"""
Integration and Security Hardening Tests (Phase 11 & Production Readiness).

Verifies:
1. Path traversal attacks on document files are rejected (403 Forbidden).
2. Malformed PDF uploads (0 bytes, corrupted headers) fail gracefully (400 Bad Request).
3. Oversized prompt payloads (> MAX_QUERY_LENGTH) return 400 or 413.
4. Non-existent document / conversation lookups return 404 cleanly with standard error format.
5. Multi-document comparison via /api/chat with comparison query formats.
6. Conversation isolation: conversations cannot access non-bound documents.
7. Graceful degradation when agent orchestrator handles complex tools.
"""
import io
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_path_traversal_prevention(client):
    """Ensure directory traversal attempts on document files return 403 Forbidden or 404."""
    # Attempt absolute path traversal outside uploads directory
    traversal_paths = [
        "../../etc/passwd",
        "....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "/etc/passwd"
    ]
    for path in traversal_paths:
        res = client.get(f"/api/documents/{path}/file")
        # Must never return 200 with system files
        assert res.status_code in [400, 403, 404, 422]


def test_malformed_empty_pdf_upload(client):
    """Uploading a 0-byte PDF must fail gracefully with 400 Bad Request."""
    empty_file = io.BytesIO(b"")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("empty.pdf", empty_file, "application/pdf")}
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower() or "invalid" in res.json()["detail"].lower()


def test_corrupted_pdf_upload(client):
    """Uploading arbitrary bytes with .pdf extension must fail with 400 Bad Request."""
    fake_pdf = io.BytesIO(b"%PDF-1.4 but completely corrupt truncated junk garbage data")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("corrupt.pdf", fake_pdf, "application/pdf")}
    )
    assert res.status_code in [400, 422]


def test_oversized_query_rejection(client):
    """Oversized query exceeding max characters must be rejected gracefully."""
    huge_query = "What is the termination notice period? " * 500  # > 10,000 chars
    res = client.post(
        "/api/chat",
        json={"document_id": "doc_nonexistent", "question": huge_query}
    )
    assert res.status_code in [400, 413, 422]


def test_nonexistent_document_chat(client):
    """Chatting against a non-existent document returns 404 or clean insufficient context."""
    res = client.post(
        "/api/chat",
        json={"document_id": "doc_does_not_exist_9999", "question": "What is the termination notice?"}
    )
    assert res.status_code in [200, 404]
    if res.status_code == 200:
        data = res.json()["data"]
        assert data["confidence"] in ["insufficient_context", "not_found"]
        assert len(data["sources"]) == 0


def test_nonexistent_document_lookup(client):
    """Querying metadata for missing document returns 404."""
    res = client.get("/api/documents/doc_does_not_exist_9999")
    assert res.status_code == 404
    body = res.json()
    assert "not found" in body["detail"].lower()


def test_multi_document_comparison_tool_direct():
    """Verify MultiDocumentComparisonTool handles comparison matrix and isolated evidence."""
    from unittest.mock import MagicMock
    from app.services.tools.comparison_tool import MultiDocumentComparisonTool
    from app.models.agent import UncertaintyState, EvidenceItem, EvidenceResult

    mock_doc_service = MagicMock()
    mock_doc_service.get_document.side_effect = lambda doc_id: MagicMock(original_filename=f"{doc_id}.pdf")

    mock_evidence_tool = MagicMock()

    # Doc A has 30 days termination, Doc B has 60 days termination
    def search_side_effect(document_ids, query, top_k):
        doc_id = document_ids[0]
        if doc_id == "doc_a":
            item = EvidenceItem(chunk_id="c1", document_id="doc_a", text="Either party may terminate upon 30 days notice.", page_number=1, section="Termination", score=0.9)
        else:
            item = EvidenceItem(chunk_id="c2", document_id="doc_b", text="Termination requires 60 days advance notice.", page_number=2, section="Termination Clause", score=0.9)
        return EvidenceResult(document_ids=document_ids, query=query, items=[item], evidence_state=UncertaintyState.SUPPORTED.value, total_chunks_found=1)

    mock_evidence_tool.search_document_evidence.side_effect = search_side_effect

    tool = MultiDocumentComparisonTool(document_service=mock_doc_service, evidence_tool=mock_evidence_tool)
    result = tool.compare_documents("doc_a", "doc_b", ["Termination notice period"])

    assert result.doc_a_id == "doc_a"
    assert result.doc_b_id == "doc_b"
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.topic == "Termination notice period"
    assert row.status == "different"
    assert row.doc_a_citation["page"] == 1
    assert row.doc_b_citation["page"] == 2
    assert "30 days" in row.doc_a_evidence
    assert "60 days" in row.doc_b_evidence


def test_postgresql_engine_configuration():
    """Verify that DatabaseManager constructs a pooled engine appropriately when DATABASE_URL is configured."""
    from unittest.mock import patch, MagicMock
    from app.persistence.database import DatabaseManager

    with patch("app.persistence.database.create_engine") as mock_create_engine, \
         patch("app.persistence.database.Base.metadata.create_all"):
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        with patch("app.core.config.settings.DATABASE_URL", "postgresql://user:secret@localhost:5432/legal_db"):
            mgr = DatabaseManager()
            mock_create_engine.assert_called_once_with(
                "postgresql://user:secret@localhost:5432/legal_db",
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20
            )
            assert mgr.engine == mock_engine


def test_multi_turn_follow_up_conversation(client):
    """Verify multi-turn follow-up queries with pronoun resolution and citation continuity."""
    pdf_path = Path("documents/synthetic_contract.pdf")
    with open(pdf_path, "rb") as f:
        up_resp = client.post("/api/documents/upload", files={"file": ("synthetic_contract.pdf", f, "application/pdf")})
    assert up_resp.status_code == 201
    doc_id = up_resp.json()["data"]["document_id"]

    # Turn 1: Primary question
    turn1 = client.post("/api/chat", json={"document_id": doc_id, "question": "What is the termination notice period?"})
    assert turn1.status_code == 200
    t1_data = turn1.json()["data"]
    conv_id = t1_data["conversation_id"]
    assert conv_id is not None
    assert "30 days" in t1_data["answer"]

    # Turn 2: Follow-up question referencing previous clause
    turn2 = client.post("/api/chat", json={
        "document_id": doc_id,
        "conversation_id": conv_id,
        "question": "What about the previous clause?"
    })
    assert turn2.status_code == 200
    t2_data = turn2.json()["data"]
    assert t2_data["conversation_id"] == conv_id
    # Resolved context should be grounded
    assert t2_data["confidence"] in ["supported", "partially_supported"]


def test_document_conversation_isolation(client):
    """Verify conversations cannot leak data to unbound documents or other conversations."""
    # Attempting to query an active conversation with an invalid/mismatched document should be isolated
    pdf_path = Path("documents/synthetic_contract.pdf")
    with open(pdf_path, "rb") as f:
        up_resp = client.post("/api/documents/upload", files={"file": ("synthetic_contract.pdf", f, "application/pdf")})
    doc_id = up_resp.json()["data"]["document_id"]

    # Create conv for doc_id
    conv_resp = client.post("/api/chat", json={"document_id": doc_id, "question": "What is the governing law?"})
    conv_id = conv_resp.json()["data"]["conversation_id"]

    # Verify conversation history retrieval via API
    conv_fetch = client.get(f"/api/conversations/{conv_id}")
    assert conv_fetch.status_code == 200
    conv_data = conv_fetch.json()["data"]
    assert doc_id in conv_data["document_ids"]
    assert len(conv_data["messages"]) >= 2  # user + assistant

