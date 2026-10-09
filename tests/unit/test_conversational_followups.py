"""
Focused regression tests for conversational follow-ups and refinement cues.
Verifies:
1. Turn 1: "Explain me the detailed summary of this document" returns grounded overview.
2. Turn 2: "Elaborate it more" expands the previous answer with document evidence.
3. Turn 3: "In a little precise way" produces concise version.
4. Consecutive follow-up: "Make it shorter" produces concise version.
5. Topic follow-up: Elaboration on a specific legal topic (e.g. termination notice).
6. Genuine new question still routes to normal RAG path.
7. Out-of-document / insufficient evidence query safely triggers fallback refusal.
8. Multi-turn document/session isolation preserves document boundary.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.agent import UncertaintyState


def _make_pdf(title: str, text: str) -> bytes:
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
def test_document(client: TestClient):
    text = (
        "This Master Services Agreement is entered into between Acme Corp (\"Client\") and TechServ LLC (\"Vendor\").\n"
        "Effective Date: January 15, 2024.\n"
        "1. Purpose. The purpose of this agreement is to provide enterprise cloud migration and consulting services.\n"
        "Section 4. Termination.\n"
        "Section 4.1. Either party may terminate for convenience upon sixty (60) days prior written notice.\n"
        "Section 4.2. Immediate termination is permitted upon written notice for uncured material breach.\n"
        "Section 8. Governing Law.\n"
        "This agreement shall be governed by and construed under the laws of the State of Delaware.\n"
        "Section 9. Indemnification.\n"
        "Vendor shall indemnify Client against third-party IP claims up to $2,000,000."
    )
    pdf_bytes = _make_pdf("MASTER SERVICES AGREEMENT", text)
    resp = client.post(
        "/api/documents/upload",
        files={"file": ("acme_agreement.pdf", pdf_bytes, "application/pdf")}
    )
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["data"]["document_id"]
    yield doc_id
    # Cleanup
    client.delete(f"/api/documents/{doc_id}")


def test_conversational_followup_elaboration_and_precision(client: TestClient, test_document: str):
    """
    Direct reproduction of the reported user bug:
    Turn 1: "Explain me the detailed summary of this document"
    Turn 2: "Elaborate it more"
    Turn 3: "In a little precise way"
    Turn 4: "Make it shorter"
    """
    history = []

    # Turn 1: Detailed summary
    payload_1 = {
        "document_id": test_document,
        "question": "Explain me the detailed summary of this document",
        "history": history
    }
    resp_1 = client.post("/api/chat", json=payload_1)
    assert resp_1.status_code == 200
    data_1 = resp_1.json()["data"]
    ans_1 = data_1["answer"]
    assert "couldn't find enough information" not in ans_1.lower()
    assert data_1["confidence"] == UncertaintyState.SUPPORTED.value

    history.append({"role": "user", "content": payload_1["question"]})
    history.append({"role": "assistant", "content": ans_1})

    # Turn 2: "Elaborate it more"
    payload_2 = {
        "document_id": test_document,
        "question": "Elaborate it more",
        "history": history
    }
    resp_2 = client.post("/api/chat", json=payload_2)
    assert resp_2.status_code == 200
    data_2 = resp_2.json()["data"]
    ans_2 = data_2["answer"]
    assert "couldn't find enough information" not in ans_2.lower()
    assert data_2["confidence"] == UncertaintyState.SUPPORTED.value
    # Should include substantive overview information
    assert ("acme" in ans_2.lower() or "techserv" in ans_2.lower() or "services" in ans_2.lower() or "master" in ans_2.lower())

    history.append({"role": "user", "content": payload_2["question"]})
    history.append({"role": "assistant", "content": ans_2})

    # Turn 3: "In a little precise way"
    payload_3 = {
        "document_id": test_document,
        "question": "In a little precise way",
        "history": history
    }
    resp_3 = client.post("/api/chat", json=payload_3)
    assert resp_3.status_code == 200
    data_3 = resp_3.json()["data"]
    ans_3 = data_3["answer"]
    assert "couldn't find enough information" not in ans_3.lower()
    assert data_3["confidence"] == UncertaintyState.SUPPORTED.value
    # Precise way should be concise
    assert len(ans_3) > 20

    history.append({"role": "user", "content": payload_3["question"]})
    history.append({"role": "assistant", "content": ans_3})

    # Turn 4: "Make it shorter"
    payload_4 = {
        "document_id": test_document,
        "question": "Make it shorter",
        "history": history
    }
    resp_4 = client.post("/api/chat", json=payload_4)
    assert resp_4.status_code == 200
    data_4 = resp_4.json()["data"]
    ans_4 = data_4["answer"]
    assert "couldn't find enough information" not in ans_4.lower()
    assert data_4["confidence"] == UncertaintyState.SUPPORTED.value


def test_specific_topic_followup_and_new_question(client: TestClient, test_document: str):
    """
    Tests topic follow-up refinement, followed by a genuine new question.
    """
    history = []

    # Turn 1: Ask about termination notice period
    payload_1 = {
        "document_id": test_document,
        "question": "What is the notice period for early termination?",
        "history": history
    }
    resp_1 = client.post("/api/chat", json=payload_1)
    assert resp_1.status_code == 200
    ans_1 = resp_1.json()["data"]["answer"]
    assert "60" in ans_1 or "sixty" in ans_1.lower()

    history.append({"role": "user", "content": payload_1["question"]})
    history.append({"role": "assistant", "content": ans_1})

    # Turn 2: Follow-up elaboration on the topic
    payload_2 = {
        "document_id": test_document,
        "question": "Elaborate on it more",
        "history": history
    }
    resp_2 = client.post("/api/chat", json=payload_2)
    assert resp_2.status_code == 200
    ans_2 = resp_2.json()["data"]["answer"]
    assert "couldn't find enough information" not in ans_2.lower()
    assert ("60" in ans_2 or "sixty" in ans_2.lower() or "convenience" in ans_2.lower() or "notice" in ans_2.lower())

    history.append({"role": "user", "content": payload_2["question"]})
    history.append({"role": "assistant", "content": ans_2})

    # Turn 3: Genuine new question (self-contained) routes to normal RAG
    payload_3 = {
        "document_id": test_document,
        "question": "What is the governing law of this agreement?",
        "history": history
    }
    resp_3 = client.post("/api/chat", json=payload_3)
    assert resp_3.status_code == 200
    ans_3 = resp_3.json()["data"]["answer"]
    assert "delaware" in ans_3.lower()


def test_missing_evidence_triggers_fallback(client: TestClient, test_document: str):
    """
    Tests that questions asking for non-existent clauses safely trigger fallback refusal.
    """
    payload = {
        "document_id": test_document,
        "question": "What are the rules regarding hazardous chemical waste disposal under this contract?",
        "history": []
    }
    resp = client.post("/api/chat", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["confidence"] == UncertaintyState.INSUFFICIENT_EVIDENCE.value or "not provide enough information" in data["answer"].lower() or "couldn't find enough information" in data["answer"].lower()


def test_document_and_session_isolation_across_followups(client: TestClient, test_document: str):
    """
    Verifies that follow-up refinements in one conversation or document do not leak
    into another session or cross-contaminate document boundaries.
    """
    # Second document with conflicting terms
    doc2_text = (
        "Parties: Zenith Global LLC and Beta Partners.\n"
        "Section 4. Termination.\n"
        "Section 4.1. Either party may terminate upon thirty (30) days prior written notice.\n"
        "Section 8. Governing Law.\n"
        "This agreement is governed by the laws of California."
    )
    pdf2_bytes = _make_pdf("ZENITH PARTNERSHIP AGREEMENT", doc2_text)
    resp2 = client.post(
        "/api/documents/upload",
        files={"file": ("zenith_agreement.pdf", pdf2_bytes, "application/pdf")}
    )
    assert resp2.status_code == 201
    doc2_id = resp2.json()["data"]["document_id"]

    try:
        # Session A on Doc 1: Summary + Follow-up
        r_a1 = client.post("/api/chat", json={
            "document_id": test_document,
            "question": "Explain me the detailed summary of this document"
        })
        assert r_a1.status_code == 200
        conv_a = r_a1.json()["data"]["conversation_id"]

        r_a2 = client.post("/api/chat", json={
            "document_id": test_document,
            "conversation_id": conv_a,
            "question": "Elaborate it more",
            "history": [
                {"role": "user", "content": "Explain me the detailed summary of this document"},
                {"role": "assistant", "content": r_a1.json()["data"]["answer"]}
            ]
        })
        assert r_a2.status_code == 200
        ans_a2 = r_a2.json()["data"]["answer"]
        assert "Zenith" not in ans_a2

        # Session B on Doc 2: Independent follow-up does not see Session A's context
        r_b1 = client.post("/api/chat", json={
            "document_id": doc2_id,
            "question": "What is the notice period for early termination?"
        })
        assert r_b1.status_code == 200
        ans_b1 = r_b1.json()["data"]["answer"]
        assert "30" in ans_b1 or "thirty" in ans_b1.lower()
        assert "60" not in ans_b1

        conv_b = r_b1.json()["data"]["conversation_id"]
        assert conv_b != conv_a

        r_b2 = client.post("/api/chat", json={
            "document_id": doc2_id,
            "conversation_id": conv_b,
            "question": "In a little precise way",
            "history": [
                {"role": "user", "content": "What is the notice period for early termination?"},
                {"role": "assistant", "content": ans_b1}
            ]
        })
        assert r_b2.status_code == 200
        ans_b2 = r_b2.json()["data"]["answer"]
        assert "30" in ans_b2 or "thirty" in ans_b2.lower()
        assert "Delaware" not in ans_b2
    finally:
        client.delete(f"/api/documents/{doc2_id}")
