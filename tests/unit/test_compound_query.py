"""
Unit and regression tests for Compound Query Partial Answerability (UNANS-005).

Verifies required behaviors:
1. Supported + unsupported compound query:
   - "What is the termination notice period and what is the severance payment amount?"
   - Supported component answered ("30 days")
   - Unsupported component explicitly stated as not found
   - Status is "partially_supported"
2. Multiple unsupported components:
   - "What is the termination notice period, severance amount, and governing court?"
   - Supported component answered
   - Both unsupported components explicitly identified
   - Status is "partially_supported"
3. Fully supported compound query:
   - "What is the termination notice period and who can terminate the agreement?"
   - Both components answered
   - Status is "supported"
4. Fully unsupported compound query:
   - "What is the severance payment amount and which court has jurisdiction?"
   - Refusal answer returned deterministically without LLM hallucination
   - Status is "insufficient_context"
   - Citations is empty []
5. Existing simple query regression:
   - "What is the termination notice period?"
   - Behaves identically to baseline with correct answer and status "supported"
6. Unrelated compound query:
   - Unrelated compound query does not pass because of incidental overlap
   - Status is "insufficient_context", 0 citations
7. Citation behavior:
   - Partially supported query attaches citations ONLY for supported component
   - Unsupported component has no fabricated citations
"""

import pytest
from pathlib import Path
import tempfile
from fastapi.testclient import TestClient

from app.main import app, app_state
from app.services.vector_store import VectorStore
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService
from app.services.citation_service import CitationService
from app.services.query_service import decompose_query, clean_subquery_topic


@pytest.fixture(scope="module")
def unans_test_env():
    """Sets up an isolated environment with synthetic_contract.pdf indexed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        upload_dir = tmp_path / "uploads"
        vector_dir = tmp_path / "vector_store"
        upload_dir.mkdir()
        vector_dir.mkdir()

        with TestClient(app) as client:
            vs = VectorStore(storage_dir=vector_dir)
            emb = EmbeddingService()
            pdf_s = PDFService()
            chunk_s = ChunkingService()
            doc_s = DocumentService(pdf_s, chunk_s, emb, vs)
            doc_s.upload_dir = upload_dir
            doc_s.metadata_file = upload_dir / "documents_meta.json"
            doc_s.documents = {}
            doc_s._hash_to_id = {}
            ret_s = RetrievalService(emb, vs)
            llm_s = LLMService()
            cite_s = CitationService()

            # Swap in isolated services into app_state
            app_state["vector_store"] = vs
            app_state["embedding_service"] = emb
            app_state["pdf_service"] = pdf_s
            app_state["chunking_service"] = chunk_s
            app_state["document_service"] = doc_s
            app_state["retrieval_service"] = ret_s
            app_state["llm_service"] = llm_s
            app_state["citation_service"] = cite_s

            pdf_path = Path("documents/synthetic_contract.pdf")
            with open(pdf_path, "rb") as f:
                up_resp = client.post(
                    "/api/documents/upload",
                    files={"file": (pdf_path.name, f, "application/pdf")}
                )
            assert up_resp.status_code == 201
            doc_id = up_resp.json()["data"]["document_id"]

            yield {
                "client": client,
                "doc_id": doc_id,
                "vector_store": vs,
                "embedding_service": emb,
                "retrieval_service": ret_s
            }


# Unit tests for query decomposition utility
def test_query_decomposition_simple():
    """Simple questions remain single-element lists."""
    q = "What is the termination notice period?"
    assert decompose_query(q) == ["What is the termination notice period?"]


def test_query_decomposition_interrogative_compound():
    """Compound questions with interrogative conjunctions decompose accurately."""
    q = "What is the termination notice period and what is the severance payment amount?"
    decomposed = decompose_query(q)
    assert len(decomposed) == 2
    assert decomposed[0] == "What is the termination notice period?"
    assert "severance payment amount" in decomposed[1]


def test_query_decomposition_oxford_comma():
    """Oxford-comma list of 3+ requirements decomposes into distinct sub-questions."""
    q = "What is the termination notice period, severance amount, and governing court?"
    decomposed = decompose_query(q)
    assert len(decomposed) == 3
    assert "termination notice period" in decomposed[0]
    assert "severance amount" in decomposed[1]
    assert "governing court" in decomposed[2]


# Test 1 — Supported + unsupported compound query
def test_case_b_partially_supported_compound_query(unans_test_env):
    """
    Test 1: One supported component + one unsupported component.
    Expected:
    - termination notice answered (contains '30 days')
    - severance amount explicitly unsupported
    - overall status == 'partially_supported'
    """
    client = unans_test_env["client"]
    doc_id = unans_test_env["doc_id"]
    q = "What is the termination notice period and what is the severance payment amount?"

    resp = client.post("/api/chat", json={"document_id": doc_id, "question": q})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["confidence"] == "partially_supported"
    assert "30 days" in data["answer"]
    assert "severance payment amount" in data["answer"].lower()
    assert "not found in the provided document" in data["answer"].lower()
    assert len(data["sources"]) >= 1


# Test 2 — Multiple unsupported components
def test_case_c_multiple_unsupported_components(unans_test_env):
    """
    Test 2: One supported component + multiple unsupported components.
    Expected:
    - status == 'partially_supported'
    - termination notice answered
    - both unsupported components explicitly identified
    """
    client = unans_test_env["client"]
    doc_id = unans_test_env["doc_id"]
    q = "What is the termination notice period, severance amount, and governing court?"

    resp = client.post("/api/chat", json={"document_id": doc_id, "question": q})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["confidence"] == "partially_supported"
    assert "30 days" in data["answer"]
    assert "severance amount" in data["answer"].lower()
    assert "governing court" in data["answer"].lower()
    assert "not found in the provided document" in data["answer"].lower()


# Test 3 — Fully supported compound query
def test_case_a_fully_supported_compound_query(unans_test_env):
    """
    Test 3: Both components supported in document.
    Expected:
    - status == 'supported'
    - both questions answered
    """
    client = unans_test_env["client"]
    doc_id = unans_test_env["doc_id"]
    q = "What is the termination notice period and who can terminate the agreement?"

    resp = client.post("/api/chat", json={"document_id": doc_id, "question": q})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["confidence"] == "supported"
    assert "30 days" in data["answer"]
    assert "either party" in data["answer"].lower()
    assert "not found" not in data["answer"].lower()


# Test 4 — Fully unsupported compound query
def test_case_d_fully_unsupported_compound_query(unans_test_env):
    """
    Test 4: Neither component supported in document.
    Expected:
    - status == 'insufficient_context'
    - standard refusal message
    - 0 citations returned
    """
    client = unans_test_env["client"]
    doc_id = unans_test_env["doc_id"]
    q = "What is the severance payment amount and which court has jurisdiction?"

    resp = client.post("/api/chat", json={"document_id": doc_id, "question": q})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["confidence"] == "insufficient_context"
    assert "couldn't find enough information" in data["answer"].lower()
    assert data["sources"] == []


# Test 5 — Existing simple query regression
def test_case_e_existing_simple_query(unans_test_env):
    """
    Test 5: Normal single question query continues to behave exactly as before.
    """
    client = unans_test_env["client"]
    doc_id = unans_test_env["doc_id"]
    q = "What is the termination notice period?"

    resp = client.post("/api/chat", json={"document_id": doc_id, "question": q})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["confidence"] == "supported"
    assert "30 days" in data["answer"]
    assert len(data["sources"]) >= 1


# Test 6 — Unrelated compound query
def test_case_f_unrelated_compound_query(unans_test_env):
    """
    Test 6: Compound question with completely unrelated topics refuses.
    """
    client = unans_test_env["client"]
    doc_id = unans_test_env["doc_id"]
    q = "What is the protocol for launching a rocket and what is the employee dress code?"

    resp = client.post("/api/chat", json={"document_id": doc_id, "question": q})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["confidence"] == "insufficient_context"
    assert "couldn't find enough information" in data["answer"].lower()
    assert data["sources"] == []


# Test 7 — Citation integrity for partially supported query
def test_case_g_citation_behavior_partially_supported(unans_test_env):
    """
    Test 7: For partially supported compound query:
    - Citations point only to evidence supporting the supported component
    - No fabricated citations for unsupported component
    """
    client = unans_test_env["client"]
    doc_id = unans_test_env["doc_id"]
    q = "What is the termination notice period and what is the severance payment amount?"

    resp = client.post("/api/chat", json={"document_id": doc_id, "question": q})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["confidence"] == "partially_supported"
    sources = data["sources"]
    assert len(sources) >= 1
    # Check that returned citations are from Termination clause
    termination_found = any("termination" in s.get("section", "").lower() or "30 days" in s.get("snippet", "").lower() for s in sources)
    assert termination_found
    # Check that no citation has severance
    for s in sources:
        assert "severance" not in s.get("snippet", "").lower()

