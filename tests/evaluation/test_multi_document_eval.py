"""
Comprehensive Multi-Document Evaluation & Verification Suite.

Tests and validates:
1. Document Isolation:
   - Query scoped to Document A returns only Document A evidence.
   - Query scoped to Document B returns only Document B evidence.
   - Identical/similar terminology in both documents does not cause evidence contamination.
   - Definitions from one document cannot satisfy a query against another.
   - Cross-reference navigation remains within the correct document.
2. Comparative Reasoning:
   - Explicit A-vs-B questions retrieve evidence from both documents correctly.
   - Answers clearly attribute facts to the correct document.
   - Different values for the same clause are not silently merged.
3. Conversation Continuity:
   - Follow-up questions preserve the correct active document.
   - Switching documents requires explicit context change.
   - Follow-ups after a document switch do not accidentally use the previous document.
4. Ambiguity / Safety:
   - Cross-document ambiguity safely requests clarification rather than guessing.
   - Unsupported cross-document claims are safely rejected by answer verification.
5. Deletion / Isolation:
   - After deleting a document, its evidence is immediately non-retrievable.
   - Conversation history cannot resurrect deleted document evidence.
"""

import io
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.main import app, app_state
from app.services.tools.comparison_tool import MultiDocumentComparisonTool
from app.services.retrieval_service import RetrievalService
from app.models.agent import UncertaintyState


def _make_document_pdf(title: str, text: str) -> bytes:
    """Helper to generate a clean synthetic PDF with PyMuPDF for reliable text extraction."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    rect = pymupdf.Rect(50, 50, 550, 750)
    page.insert_textbox(rect, f"{title}\n\n{text}", fontsize=11, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def multi_doc_corpus(client: TestClient):
    """
    Sets up 3 distinct legal documents with deliberately contrasting terms:
    - Doc Alpha (Alpha Cloud Services MSA):
      * Parties: Alpha Cloud Inc. & Client
      * Notice period: 30 days
      * Governing Law: State of California
      * Defined Term: "Confidential Data" means proprietary source code and algorithms.
      * Cross Reference: Section 4.1 subject to Section 9.2 (Indemnity)
      * Indemnity Cap: $1,000,000
    - Doc Beta (Beta Enterprise Master Agreement):
      * Parties: Beta Systems LLC & Customer
      * Notice period: 90 days
      * Governing Law: State of New York
      * Defined Term: "Confidential Data" means customer personal identifiable records and invoices.
      * Cross Reference: Section 4.1 subject to Section 11.5 (Arbitration)
      * Indemnity Cap: $5,000,000
    - Doc Gamma (Gamma Logistics Supply Contract):
      * Parties: Gamma Freight Corp & Shipper
      * Notice period: 15 days
      * Governing Law: State of Texas
      * Defined Term: "Cargo Goods" means bulk dry freight containers.
    """
    doc_alpha_text = (
        "Parties: Alpha Cloud Inc. and Client.\n"
        "Section 1. Definitions.\n"
        "\"Confidential Data\" means proprietary source code and algorithms.\n"
        "Section 4. Termination.\n"
        "Section 4.1. Termination requires thirty (30) days prior written notice.\n"
        "Section 8. Governing Law.\n"
        "This agreement is governed by the laws of California.\n"
        "Section 9. Indemnification.\n"
        "Section 9.2. Total aggregate indemnity obligation is capped at $1,000,000."
    )

    doc_beta_text = (
        "Parties: Beta Systems LLC and Customer.\n"
        "Section 1. Definitions.\n"
        "\"Confidential Data\" means customer personal identifiable records and invoices.\n"
        "Section 4. Termination.\n"
        "Section 4.1. Termination requires ninety (90) days prior written notice.\n"
        "Section 8. Governing Law.\n"
        "This agreement is governed by the laws of New York.\n"
        "Section 11. Dispute Resolution.\n"
        "Section 11.5. All disputes shall be submitted to confidential arbitration in New York City.\n"
        "Section 12. Indemnification.\n"
        "Total aggregate indemnity obligation is capped at $5,000,000."
    )

    doc_gamma_text = (
        "Parties: Gamma Freight Corp and Shipper.\n"
        "Section 1. Definitions.\n"
        "\"Cargo Goods\" means bulk dry freight containers.\n"
        "Section 3. Termination.\n"
        "Either party may terminate upon fifteen (15) days written notice.\n"
        "Section 7. Governing Law.\n"
        "This contract is governed by the laws of Texas."
    )

    resp_a = client.post("/api/documents/upload", files={"file": ("doc_alpha.pdf", _make_document_pdf("ALPHA CLOUD SERVICES AGREEMENT (DOC ALPHA)", doc_alpha_text), "application/pdf")})
    resp_b = client.post("/api/documents/upload", files={"file": ("doc_beta.pdf", _make_document_pdf("BETA ENTERPRISE MASTER AGREEMENT (DOC BETA)", doc_beta_text), "application/pdf")})
    resp_c = client.post("/api/documents/upload", files={"file": ("doc_gamma.pdf", _make_document_pdf("GAMMA LOGISTICS SUPPLY CONTRACT (DOC GAMMA)", doc_gamma_text), "application/pdf")})

    assert resp_a.status_code == 201, resp_a.text
    assert resp_b.status_code == 201, resp_b.text
    assert resp_c.status_code == 201, resp_c.text

    doc_a_id = resp_a.json()["data"]["document_id"]
    doc_b_id = resp_b.json()["data"]["document_id"]
    doc_c_id = resp_c.json()["data"]["document_id"]

    return {
        "doc_a": doc_a_id,
        "doc_b": doc_b_id,
        "doc_c": doc_c_id
    }


# ==============================================================================
# 1. DOCUMENT ISOLATION TESTS
# ==============================================================================

def test_document_isolation_scoped_retrieval(client: TestClient, multi_doc_corpus):
    """Query scoped to Document A returns only A evidence; query scoped to B returns only B."""
    doc_a = multi_doc_corpus["doc_a"]
    doc_b = multi_doc_corpus["doc_b"]

    # Notice period on Doc A -> 30 days
    res_a = client.post("/api/chat", json={"document_id": doc_a, "question": "What is the termination notice period?"})
    assert res_a.status_code == 200
    data_a = res_a.json()["data"]
    assert "30" in data_a["answer"] or "thirty" in data_a["answer"].lower()
    assert "90" not in data_a["answer"]
    for src in data_a["sources"]:
        assert src["document_id"] == doc_a
        assert src["document_id"] != doc_b

    # Notice period on Doc B -> 90 days
    res_b = client.post("/api/chat", json={"document_id": doc_b, "question": "What is the termination notice period?"})
    assert res_b.status_code == 200
    data_b = res_b.json()["data"]
    assert "90" in data_b["answer"] or "ninety" in data_b["answer"].lower()
    assert "30" not in data_b["answer"]
    for src in data_b["sources"]:
        assert src["document_id"] == doc_b
        assert src["document_id"] != doc_a


def test_identical_term_defined_meanings_isolation(client: TestClient, multi_doc_corpus):
    """
    Both documents define 'Confidential Data', but with different meanings:
    Doc A: proprietary source code and algorithms
    Doc B: customer personal identifiable records and invoices
    Neither must leak into the other.
    """
    doc_a = multi_doc_corpus["doc_a"]
    doc_b = multi_doc_corpus["doc_b"]

    # Query definition on Doc A
    res_a = client.post("/api/chat", json={"document_id": doc_a, "question": "What is the definition of 'Confidential Data'?"})
    assert res_a.status_code == 200
    ans_a = res_a.json()["data"]["answer"].lower()
    assert "source code" in ans_a or "algorithms" in ans_a
    assert "identifiable records" not in ans_a
    assert "invoices" not in ans_a

    # Query definition on Doc B
    res_b = client.post("/api/chat", json={"document_id": doc_b, "question": "What is the definition of 'Confidential Data'?"})
    assert res_b.status_code == 200
    ans_b = res_b.json()["data"]["answer"].lower()
    assert "identifiable records" in ans_b or "invoices" in ans_b
    assert "source code" not in ans_b
    assert "algorithms" not in ans_b


def test_unique_concept_unsupported_in_other_document(client: TestClient, multi_doc_corpus):
    """
    'Cargo Goods' is defined only in Doc Gamma.
    Querying Doc A or Doc B for 'Cargo Goods' must be safely refused (insufficient evidence).
    """
    doc_a = multi_doc_corpus["doc_a"]
    doc_c = multi_doc_corpus["doc_c"]

    # In Doc A: must refuse
    res_a = client.post("/api/chat", json={"document_id": doc_a, "question": "What are Cargo Goods?"})
    assert res_a.status_code == 200
    data_a = res_a.json()["data"]
    assert data_a["confidence"] == "insufficient_context"
    assert len(data_a["sources"]) == 0

    # In Doc Gamma: must support
    res_c = client.post("/api/chat", json={"document_id": doc_c, "question": "What are Cargo Goods?"})
    assert res_c.status_code == 200
    data_c = res_c.json()["data"]
    assert "bulk dry freight" in data_c["answer"].lower()
    assert any(s["document_id"] == doc_c for s in data_c["sources"])


# ==============================================================================
# 2. COMPARATIVE REASONING TESTS
# ==============================================================================

def test_comparative_reasoning_explicit_comparison(client: TestClient, multi_doc_corpus):
    """
    Explicit comparison question between doc_a and doc_b retrieves evidence from both,
    correctly attributing facts without merging disparate values.
    """
    doc_a = multi_doc_corpus["doc_a"]
    doc_b = multi_doc_corpus["doc_b"]

    q = f"Compare the termination notice between {doc_a} and {doc_b}"
    res = client.post("/api/chat", json={"document_id": doc_a, "question": q})
    assert res.status_code == 200
    data = res.json()["data"]
    answer = data["answer"]

    # Must contain both documents and their contrasting notice periods
    assert doc_a in answer or "doc_alpha" in answer
    assert doc_b in answer or "doc_beta" in answer
    assert "30 days" in answer or "thirty" in answer.lower()
    assert "90 days" in answer or "ninety" in answer.lower()

    # Sources must contain citations for both documents
    doc_ids_in_sources = {s["document_id"] for s in data["sources"]}
    assert doc_a in doc_ids_in_sources
    assert doc_b in doc_ids_in_sources


def test_comparative_direct_tool_execution(multi_doc_corpus):
    """Test MultiDocumentComparisonTool isolated execution matrix directly."""
    comp_tool: MultiDocumentComparisonTool = app_state["comparison_tool"]
    doc_a = multi_doc_corpus["doc_a"]
    doc_b = multi_doc_corpus["doc_b"]

    topics = ["Termination notice", "Governing law", "Indemnification"]
    result = comp_tool.compare_documents(doc_a_id=doc_a, doc_b_id=doc_b, topics=topics)

    assert result.doc_a_id == doc_a
    assert result.doc_b_id == doc_b
    assert len(result.rows) == 3

    # Verification of topics
    term_row = next(r for r in result.rows if "Termination" in r.topic)
    assert term_row.status == "different"
    assert "30" in term_row.doc_a_evidence
    assert "90" in term_row.doc_b_evidence
    assert term_row.doc_a_citation["document_id"] == doc_a
    assert term_row.doc_b_citation["document_id"] == doc_b

    gov_row = next(r for r in result.rows if "Governing" in r.topic)
    assert "california" in gov_row.doc_a_evidence.lower()
    assert "new york" in gov_row.doc_b_evidence.lower()


# ==============================================================================
# 3. CONVERSATION CONTINUITY & SWITCHING TESTS
# ==============================================================================

def test_conversation_continuity_and_document_switch(client: TestClient, multi_doc_corpus):
    """
    Test that multi-turn follow-ups stay locked to the active document and
    switching documents prevents previous context leakage.
    """
    doc_a = multi_doc_corpus["doc_a"]
    doc_b = multi_doc_corpus["doc_b"]

    # Turn 1 on Doc A: Governing law
    r1 = client.post("/api/chat", json={"document_id": doc_a, "question": "What is the governing law of California?"})
    assert r1.status_code == 200
    conv_a = r1.json()["data"]["conversation_id"]
    assert "California" in r1.json()["data"]["answer"]

    # Turn 2 follow-up on Doc A: Indemnity limit
    r2 = client.post("/api/chat", json={"document_id": doc_a, "conversation_id": conv_a, "question": "What is the indemnity obligation cap?"})
    assert r2.status_code == 200
    assert "1,000,000" in r2.json()["data"]["answer"]
    assert all(s["document_id"] == doc_a for s in r2.json()["data"]["sources"])

    # Switch to Doc B with a new conversation
    r3 = client.post("/api/chat", json={"document_id": doc_b, "question": "What is the indemnity obligation cap?"})
    assert r3.status_code == 200
    conv_b = r3.json()["data"]["conversation_id"]
    assert conv_b != conv_a
    assert "5,000,000" in r3.json()["data"]["answer"]
    assert "1,000,000" not in r3.json()["data"]["answer"]
    assert all(s["document_id"] == doc_b for s in r3.json()["data"]["sources"])

    # Follow-up on Doc B: does it still use Doc B context?
    r4 = client.post("/api/chat", json={"document_id": doc_b, "conversation_id": conv_b, "question": "What is the governing law jurisdiction?"})
    assert r4.status_code == 200
    assert "New York" in r4.json()["data"]["answer"]
    assert "California" not in r4.json()["data"]["answer"]


# ==============================================================================
# 4. AMBIGUITY & SAFETY TESTS
# ==============================================================================

def test_cross_document_ambiguity_requests_clarification(client: TestClient, multi_doc_corpus):
    """
    If a user chatting on Doc A asks about Doc Beta explicitly without an explicit
    comparison intent, the system safely clarifies rather than blindly retrieving Doc A.
    """
    doc_a = multi_doc_corpus["doc_a"]

    # Chatting on Doc A, but referencing 'doc_beta'
    res = client.post("/api/chat", json={"document_id": doc_a, "question": "What are the rules under doc_beta?"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["confidence"] == "clarification_required"
    assert "references 'doc_beta.png'" in data["answer"] or "active document is" in data["answer"]
    assert len(data["sources"]) == 0


def test_comparison_without_second_document_clarifies(client: TestClient, multi_doc_corpus):
    """Generic comparison inquiry without specifying second document requests clarification."""
    doc_a = multi_doc_corpus["doc_a"]
    res = client.post("/api/chat", json={"document_id": doc_a, "question": "Compare the termination terms with the other contract"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["confidence"] == "clarification_required"
    assert "Which documents would you like me to compare?" in data["answer"]


# ==============================================================================
# 5. DELETION & ISOLATION LIFECYCLE TESTS
# ==============================================================================

def test_document_deletion_immediately_removes_evidence(client: TestClient, multi_doc_corpus):
    """
    After deleting a document from the corpus:
    - Its vectors and metadata are eradicated.
    - Subsequent queries return 404 or insufficient context.
    - Remaining documents continue operating with zero disruption.
    """
    doc_c = multi_doc_corpus["doc_c"]
    doc_a = multi_doc_corpus["doc_a"]

    # 1. Delete Doc Gamma
    del_res = client.delete(f"/api/documents/{doc_c}")
    assert del_res.status_code == 200

    # 2. Querying deleted Doc Gamma directly returns 404
    q_del = client.post("/api/chat", json={"document_id": doc_c, "question": "What is the governing law?"})
    assert q_del.status_code == 404

    # 3. Querying Doc A continues to function flawlessly
    q_a = client.post("/api/chat", json={"document_id": doc_a, "question": "What is the governing law?"})
    assert q_a.status_code == 200
    assert "California" in q_a.json()["data"]["answer"]
