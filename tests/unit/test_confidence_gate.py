"""
Unit and integration tests for the RAG Semantic Confidence Gate.

Verifies:
1. Strong semantic match (top_score >= 0.35 with >= 1 content word match).
2. Exact strong threshold boundary (top_score == 0.35).
3. Just below strong threshold (top_score == 0.3499 fails if overlap < 0.35).
4. Secondary semantic/lexical rule (top_score >= 0.10 and overlap >= 35%).
5. Exact overlap boundary (overlap == 0.35).
6. Just below overlap boundary (overlap < 0.35 fails if top_score < 0.35).
7. Superficial generic-term match (e.g., "client" with low score 0.1795 and low overlap fails).
8. Below minimum score (top_score < 0.10 fails even with overlap).
9. No content match (top_score >= 0.35 with 0 matching words fails).
10. Empty retrieval downstream behavior (retrieval=[], LLM not called, refusal returned, confidence="insufficient_context", sources=0).
11. Configuration verification (thresholds driven by settings, monkeypatchable).
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app, app_state
from app.core.config import settings
from app.models.document import DocumentChunk
from app.services.retrieval_service import RetrievalService
from app.services.vector_store import VectorStore
from app.services.embedding_service import EmbeddingService, MockEmbeddingProvider
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.llm_service import LLMService
from app.services.citation_service import CitationService


def make_dummy_chunk(
    chunk_id: str = "c1",
    section: str = "Confidentiality",
    text: str = "Each party agrees to hold Confidential Information in strict confidence."
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="doc_test",
        document_name="test.pdf",
        page_number=1,
        section=section,
        text=text
    )


@pytest.fixture
def mock_retrieval_service():
    emb = EmbeddingService()
    emb.provider = MockEmbeddingProvider(dimension=16)
    vs = MagicMock(spec=VectorStore)
    return RetrievalService(emb, vs)


# =====================================================================
# 1-9: Semantic Confidence Gate Unit Tests (is_context_relevant)
# =====================================================================

def test_gate_case_1_strong_semantic_match(mock_retrieval_service):
    """Case 1: top_score >= 0.35 and >=1 content match passes the gate."""
    query = "What is the confidentiality non-disclosure obligation duration?"
    # Content words in query: {'confidentiality', 'non-disclosure', 'obligation', 'duration'}
    chunk = make_dummy_chunk(
        section="Confidentiality",
        text="All proprietary information must be kept in strict confidence."
    )
    # Matching words: {'confidentiality', 'confidence'} (or 'confidentiality' in section)
    # top_score 0.40 >= 0.35
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.40)]) is True


def test_gate_case_2_exact_strong_threshold(mock_retrieval_service):
    """Case 2: top_score == 0.35 with >=1 content match passes."""
    query = "What is the governing law of the contract?"
    # Content words: {'governing', 'law', 'contract'}
    chunk = make_dummy_chunk(
        section="Governing Law",
        text="This agreement is governed by the state of Delaware."
    )
    # Matching words: {'governing', 'law'}
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.35)]) is True


def test_gate_case_3_just_below_strong_threshold(mock_retrieval_service):
    """Case 3: top_score == 0.3499 fails if secondary overlap is below 35%."""
    # Query with 5 content words: {'penalty', 'delivery', 'deadline', 'supplier', 'milestone'}
    query = "What is the penalty for delivery deadline from supplier on milestone?"
    # Chunk only matches 1 word: 'delivery' (overlap = 1/5 = 20% < 35%)
    chunk = make_dummy_chunk(
        section="Delivery",
        text="Products shall be scheduled for delivery on regular working days."
    )
    # 0.3499 < 0.35 and overlap 20% < 35% -> MUST FAIL
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.3499)]) is False


def test_gate_case_4_secondary_semantic_lexical_rule(mock_retrieval_service):
    """Case 4: top_score >= 0.10 and content_word_overlap >= 35% passes."""
    # Query with 4 content words: {'cure', 'period', 'material', 'breach'}
    query = "What is the cure period for a material breach?"
    # Chunk text contains 'cure', 'material', 'breach' (3/4 = 75% overlap >= 35%)
    chunk = make_dummy_chunk(
        section="Termination",
        text="Either party may terminate upon material breach if failure to cure within fifteen days."
    )
    # top_score 0.14 >= 0.10, overlap 75% >= 35% -> MUST PASS
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.14)]) is True


def test_gate_case_5_exact_overlap_boundary(mock_retrieval_service):
    """Case 5: content_word_overlap == 35% (exactly meets MIN_CONTENT_WORD_OVERLAP) with score >= 0.10 passes."""
    # 20 distinct words: 7 matching = 7/20 = 0.35 exactly
    query_words_list = [
        "apple", "banana", "cherry", "date", "elderberry", "fig", "grape",
        "honeydew", "kiwi", "lemon", "mango", "nectarine", "orange", "papaya",
        "quince", "raspberry", "strawberry", "tangerine", "ugli", "vanilla"
    ]
    query = " ".join(query_words_list)
    matching_7 = " ".join(query_words_list[:7])  # 7 / 20 = 0.35 exactly
    chunk = make_dummy_chunk(section="", text=matching_7)

    # Score is 0.15 (between 0.10 and 0.35)
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.15)]) is True


def test_gate_case_6_just_below_overlap_boundary(mock_retrieval_service):
    """Case 6: content_word_overlap < 35% fails when top_score < 0.35."""
    # 20 distinct words: 6 matching = 6/20 = 0.30 < 0.35
    query_words_list = [
        "apple", "banana", "cherry", "date", "elderberry", "fig", "grape",
        "honeydew", "kiwi", "lemon", "mango", "nectarine", "orange", "papaya",
        "quince", "raspberry", "strawberry", "tangerine", "ugli", "vanilla"
    ]
    query = " ".join(query_words_list)
    matching_6 = " ".join(query_words_list[:6])  # 6 / 20 = 0.30
    chunk = make_dummy_chunk(section="", text=matching_6)

    # Score 0.25 (below 0.35, above 0.10)
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.25)]) is False


def test_gate_case_7_superficial_generic_term_match(mock_retrieval_service):
    """Case 7: Generic term match like UNANS-004 ('client', score 0.1795, low overlap) fails."""
    # Query: 5 content words: {'employee', 'non', 'solicitation', 'restrictions', 'client'}
    query = "What are the employee non-solicitation restrictions for the client?"
    # Irrelevant chunk matching only 'client' (1/5 = 20% overlap < 35%)
    chunk = make_dummy_chunk(
        section="Intellectual Property",
        text="All deliverables shall belong solely to the client as work made for hire."
    )
    # Score 0.1795 (as observed with TF-IDF against IP clause)
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.1795)]) is False


def test_gate_case_8_below_minimum_score(mock_retrieval_service):
    """Case 8: top_score < 0.10 fails even if content word overlap is 100%."""
    query = "What is the liability cap?"
    # Content words: {'liability', 'cap'}
    chunk = make_dummy_chunk(
        section="Liability",
        text="The aggregate liability cap is one hundred thousand dollars."
    )
    # Even with 100% overlap, score 0.08 < 0.10 fails
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.08)]) is False


def test_gate_case_9_no_content_match_fails_even_with_high_score(mock_retrieval_service):
    """Case 9: top_score >= 0.35 fails if there are ZERO matching content words."""
    query = "What is the employee pension retirement plan?"
    # Content words: {'employee', 'pension', 'retirement', 'plan'}
    chunk = make_dummy_chunk(
        section="Jurisdiction",
        text="Arbitration shall occur in Wilmington Delaware under AAA rules."
    )
    # Even if score were 0.50 (e.g. dense embedding hallucination on stop words/structure), 0 matching words must fail
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.50)]) is False


def test_gate_empty_results_and_empty_query(mock_retrieval_service):
    """Edge cases: empty results returns False, empty content query returns True."""
    assert mock_retrieval_service.is_context_relevant("test query", []) is False
    # Query with only stop words: 'what is this'
    assert mock_retrieval_service.is_context_relevant("what is this", [(make_dummy_chunk(), 0.5)]) is True


# =====================================================================
# 10: Downstream Behavior on Rejected Retrieval (Empty retrieval)
# =====================================================================

def test_downstream_empty_retrieval_bypasses_llm_and_refuses(monkeypatch):
    """
    Case 10: When retrieval produces [] (or gate rejects),
    - LLM generation is NOT invoked (assert mock LLM call count == 0)
    - Response has refusal answer
    - confidence == 'insufficient_context'
    - sources == []
    """
    with TestClient(app) as client:
        # Create isolated services
        emb = EmbeddingService()
        emb.provider = MockEmbeddingProvider(dimension=16)
        vs = MagicMock(spec=VectorStore)
        ret_s = RetrievalService(emb, vs)

        # Mock vector store search to return irrelevant chunk that fails the gate
        dummy_chunk = make_dummy_chunk(
            section="Intellectual Property",
            text="All deliverables belong solely to the client."
        )
        # 1 match ('client') out of 5 query content words, score 0.1795 -> gate rejects, retrieve returns []
        vs.search.return_value = [(dummy_chunk, 0.1795)]

        mock_llm_service = MagicMock(spec=LLMService)
        cite_s = CitationService()
        mock_doc_service = MagicMock(spec=DocumentService)
        mock_doc = MagicMock()
        mock_doc_service.get_document.return_value = mock_doc

        # Swap into app_state
        monkeypatch.setitem(app_state, "vector_store", vs)
        monkeypatch.setitem(app_state, "embedding_service", emb)
        monkeypatch.setitem(app_state, "retrieval_service", ret_s)
        monkeypatch.setitem(app_state, "llm_service", mock_llm_service)
        monkeypatch.setitem(app_state, "citation_service", cite_s)
        monkeypatch.setitem(app_state, "document_service", mock_doc_service)

        resp = client.post(
            "/api/chat",
            json={
                "document_id": "doc_123",
                "question": "What are the employee non-solicitation restrictions for the client?"
            }
        )
        assert resp.status_code == 200
        data = resp.json()["data"]

        # Crucial assertions:
        # 1. LLM was NEVER invoked
        mock_llm_service.generate_answer.assert_not_called()

        # 2. Refusal answer
        assert "couldn't find enough information" in data["answer"].lower()

        # 3. Confidence is insufficient_context
        assert data["confidence"] == "insufficient_context"

        # 4. Zero sources
        assert data["sources"] == []


# =====================================================================
# 11: Configuration Verification Tests
# =====================================================================

def test_confidence_gate_thresholds_configurable(mock_retrieval_service, monkeypatch):
    """Verify that thresholds are read from settings and not hardcoded."""
    # Check default config values
    assert settings.RELEVANCE_CONFIDENCE_THRESHOLD == 0.35
    assert settings.MIN_CONTENT_WORD_OVERLAP == 0.35
    assert settings.SIMILARITY_THRESHOLD == 0.10

    # Query with 5 content words: {'alpha', 'bravo', 'charlie', 'delta', 'echo'}
    query = "alpha bravo charlie delta echo"
    # Chunk with only 1 match: 'alpha' -> overlap is 1/5 = 20% (< 35%)
    chunk = make_dummy_chunk(
        section="",
        text="alpha foxtrot golf hotel india"
    )

    # Under default settings:
    # Score 0.40 >= 0.35 with 1 match passes
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.40)]) is True

    # Monkeypatch RELEVANCE_CONFIDENCE_THRESHOLD to 0.50
    # Now score 0.40 < 0.50 and overlap 20% < 35%, so it must FAIL
    monkeypatch.setattr(settings, "RELEVANCE_CONFIDENCE_THRESHOLD", 0.50)
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.40)]) is False

    # Monkeypatch MIN_CONTENT_WORD_OVERLAP to 0.15
    # Now overlap 20% >= 15%, and score 0.40 >= 0.10, so it must PASS
    monkeypatch.setattr(settings, "MIN_CONTENT_WORD_OVERLAP", 0.15)
    assert mock_retrieval_service.is_context_relevant(query, [(chunk, 0.40)]) is True
