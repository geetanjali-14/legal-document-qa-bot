"""
Pytest Integration for Legal RAG Evaluation Benchmark Suite (OPT-018).

Tests:
1. End-to-end execution of the benchmark suite on isolated storage.
2. Individual evaluation category tests:
   - Direct fact clause extraction
   - Multi-clause context extraction
   - Unanswerable question refusal contract
   - Adversarial prompt injection defense / rejection
   - Citation metadata provenance (doc, page, section, snippet)
   - Retrieval quality and top chunk ranking
3. Telemetry and cost tracking (actual vs estimated vs unknown, non-null latencies).
4. Regression protection:
   - Dense local embedding retrieval comparability
   - Determinism verification across back-to-back runs.
"""

from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import app, app_state
from app.services.vector_store import VectorStore
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService, FastEmbedProvider
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService, MockLLMProvider
from app.services.citation_service import CitationService
from tests.evaluation.benchmark_dataset import (
    BENCHMARK_CASES,
    BenchmarkCategory,
    BenchmarkCase
)
from tests.evaluation.eval_harness import (
    evaluate_case,
    compute_benchmark_summary,
    EvaluationStatus
)


@pytest.fixture(scope="module")
def isolated_eval_env():
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
            doc_s = DocumentService(pdf_s, chunk_s, emb, vs, upload_dir=upload_dir)
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


def test_benchmark_full_suite_execution(isolated_eval_env):
    """Executes all benchmark cases and asserts summary calculation and reporting."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    results = []
    for case in BENCHMARK_CASES:
        resp = client.post("/api/chat", json={"document_id": doc_id, "question": case.question})
        assert resp.status_code == 200
        case_eval = evaluate_case(case, resp.json()["data"])
        results.append(case_eval)

    summary = compute_benchmark_summary(results)
    assert summary.total_cases == len(BENCHMARK_CASES)
    # UNANS-004 is now handled cleanly by the semantic confidence gate: 0 failures
    assert summary.failed_cases == 0
    unans_4 = next(r for r in results if r.case_id == "UNANS-004")
    assert unans_4.status == EvaluationStatus.PASS
    assert unans_4.answer_eval == EvaluationStatus.PASS
    assert unans_4.refusal_eval == EvaluationStatus.PASS
    assert unans_4.citation_eval == EvaluationStatus.PASS
    assert unans_4.grounding_eval == EvaluationStatus.PASS
    assert unans_4.actual_confidence == "insufficient_context"
    assert unans_4.actual_citation_count == 0

    # All benchmark cases must pass
    for r in results:
        assert r.status == EvaluationStatus.PASS, f"Case {r.case_id} failed: {r.notes}"


def test_benchmark_direct_fact_category(isolated_eval_env):
    """Evaluates DIRECT_FACT cases: answer, retrieval, citations."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    fact_cases = [c for c in BENCHMARK_CASES if c.category == BenchmarkCategory.DIRECT_FACT]
    for case in fact_cases:
        resp = client.post("/api/chat", json={"document_id": doc_id, "question": case.question})
        assert resp.status_code == 200
        result = evaluate_case(case, resp.json()["data"])
        assert result.answer_eval == EvaluationStatus.PASS
        assert result.retrieval_eval == EvaluationStatus.PASS
        assert result.citation_eval == EvaluationStatus.PASS
        assert result.refusal_eval == EvaluationStatus.PASS
        assert result.grounding_eval == EvaluationStatus.PASS


def test_benchmark_multi_clause_category(isolated_eval_env):
    """Evaluates MULTI_CLAUSE synthesis questions."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    multi_cases = [c for c in BENCHMARK_CASES if c.category == BenchmarkCategory.MULTI_CLAUSE]
    for case in multi_cases:
        resp = client.post("/api/chat", json={"document_id": doc_id, "question": case.question})
        assert resp.status_code == 200
        result = evaluate_case(case, resp.json()["data"])
        assert result.answer_eval == EvaluationStatus.PASS
        assert result.retrieval_eval == EvaluationStatus.PASS


def test_benchmark_unanswerable_category(isolated_eval_env):
    """Evaluates clean unanswerable cases refusing with 0 citations."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    unans_cases = [c for c in BENCHMARK_CASES if c.category == BenchmarkCategory.UNANSWERABLE]
    for case in unans_cases:
        resp = client.post("/api/chat", json={"document_id": doc_id, "question": case.question})
        assert resp.status_code == 200
        result = evaluate_case(case, resp.json()["data"])
        assert result.answer_eval == EvaluationStatus.PASS
        assert result.refusal_eval == EvaluationStatus.PASS
        assert result.actual_citation_count == 0


def test_benchmark_adversarial_category(isolated_eval_env):
    """Evaluates adversarial prompt injection and out-of-scope non-legal queries."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    advers_cases = [c for c in BENCHMARK_CASES if c.category == BenchmarkCategory.ADVERSARIAL]
    for case in advers_cases:
        resp = client.post("/api/chat", json={"document_id": doc_id, "question": case.question})
        assert resp.status_code == 200
        result = evaluate_case(case, resp.json()["data"])
        assert result.status == EvaluationStatus.PASS
        assert result.actual_citation_count == 0
        assert result.actual_confidence == "insufficient_context"


def test_benchmark_citation_integrity_category(isolated_eval_env):
    """Evaluates that citations correspond to expected document, page, and section."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    cite_cases = [c for c in BENCHMARK_CASES if c.category == BenchmarkCategory.CITATION]
    for case in cite_cases:
        resp = client.post("/api/chat", json={"document_id": doc_id, "question": case.question})
        assert resp.status_code == 200
        result = evaluate_case(case, resp.json()["data"])
        assert result.citation_eval == EvaluationStatus.PASS
        assert result.actual_citation_count >= 1


def test_benchmark_telemetry_and_latency_measurement(isolated_eval_env):
    """Verifies that telemetry captures latencies and tokens cleanly."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    case = next(c for c in BENCHMARK_CASES if c.case_id == "FACT-001")
    resp = client.post("/api/chat", json={"document_id": doc_id, "question": case.question})
    assert resp.status_code == 200
    result = evaluate_case(case, resp.json()["data"])

    # Latencies must be non-negative monotonic measurements
    assert result.total_latency_ms >= 0.0
    assert result.retrieval_latency_ms is not None and result.retrieval_latency_ms >= 0.0
    assert result.embedding_latency_ms is not None and result.embedding_latency_ms >= 0.0
    assert result.llm_latency_ms is not None and result.llm_latency_ms >= 0.0

    # Mock provider reports estimated tokens, not fake actual tokens
    assert result.token_usage_type == "estimated"
    assert result.actual_tokens is None
    assert result.estimated_tokens is not None and result.estimated_tokens > 0


def test_benchmark_determinism_across_runs(isolated_eval_env):
    """Verifies that running the same benchmark case twice yields deterministic outcomes."""
    client = isolated_eval_env["client"]
    doc_id = isolated_eval_env["doc_id"]

    case = next(c for c in BENCHMARK_CASES if c.case_id == "FACT-001")
    run1 = client.post("/api/chat", json={"document_id": doc_id, "question": case.question}).json()["data"]
    run2 = client.post("/api/chat", json={"document_id": doc_id, "question": case.question}).json()["data"]

    eval1 = evaluate_case(case, run1)
    eval2 = evaluate_case(case, run2)

    assert eval1.actual_answer == eval2.actual_answer
    assert eval1.actual_retrieved_count == eval2.actual_retrieved_count
    assert eval1.actual_citation_count == eval2.actual_citation_count
    assert eval1.status == eval2.status == EvaluationStatus.PASS

