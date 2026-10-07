import time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.errors import EmbeddingDimensionMismatchError
from app.models.document import DocumentChunk
from app.services.embedding_service import (
    EmbeddingService,
    FastEmbedProvider,
    TFIDFEmbeddingProvider,
    MockEmbeddingProvider
)
from app.services.vector_store import VectorStore
from app.services.retrieval_service import RetrievalService
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService


def test_fastembed_provider_initialization_and_shapes():
    """Verify FastEmbedProvider loads local model and returns expected dimensions."""
    provider = FastEmbedProvider(model_name="BAAI/bge-small-en-v1.5")
    texts = [
        "This Agreement may be terminated by either party upon notice.",
        "Governing law shall be Delaware state law."
    ]
    vecs = provider.embed_texts(texts)
    assert isinstance(vecs, np.ndarray)
    assert vecs.shape == (2, 384)
    assert vecs.dtype == np.float32

    q_vec = provider.embed_query("How to terminate?")
    assert isinstance(q_vec, np.ndarray)
    assert q_vec.shape == (1, 384)
    assert q_vec.dtype == np.float32

    empty_vecs = provider.embed_texts([])
    assert empty_vecs.shape == (0, 384)


def test_fastembed_synonym_retrieval(tmp_path: Path):
    """
    OPT-008 Core Acceptance: Semantic synonym retrieval.
    Query with 'cancel agreement' retrieves chunk stating 'terminate agreement'.
    """
    store = VectorStore(storage_dir=tmp_path)
    embedding_service = EmbeddingService()
    embedding_service.provider = FastEmbedProvider()

    chunks = [
        DocumentChunk(
            chunk_id="chunk_term",
            document_id="doc_synonym",
            document_name="contract.pdf",
            page_number=1,
            section="Termination",
            text="Either party may terminate this agreement upon thirty days written notice."
        ),
        DocumentChunk(
            chunk_id="chunk_comp",
            document_id="doc_synonym",
            document_name="contract.pdf",
            page_number=2,
            section="Compensation",
            text="Consultant shall be compensated at an hourly rate of two hundred dollars."
        ),
        DocumentChunk(
            chunk_id="chunk_conf",
            document_id="doc_synonym",
            document_name="contract.pdf",
            page_number=3,
            section="Confidentiality",
            text="All proprietary technical information shall remain strictly confidential."
        )
    ]

    vecs = embedding_service.embed_texts([c.text for c in chunks])
    store.add_document("doc_synonym", chunks, vecs)

    retrieval = RetrievalService(embedding_service, store)

    # Query uses 'cancel' which does not appear verbatim in chunk text
    results = retrieval.retrieve(
        document_id="doc_synonym",
        query="How do I cancel this agreement?",
        top_k=2,
        threshold=0.1
    )

    assert len(results) > 0
    top_chunk, score = results[0]
    assert top_chunk.chunk_id == "chunk_term"
    assert top_chunk.section == "Termination"
    assert "terminate this agreement" in top_chunk.text
    assert score > 0.4


def test_fastembed_query_latency_under_50ms():
    """OPT-008 Acceptance: Local CPU query embedding latency < 50ms."""
    provider = FastEmbedProvider()
    # Warmup invocation
    provider.embed_query("warmup query")

    latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        provider.embed_query("What is the governing law of this contract?")
        latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_latency = sum(latencies) / len(latencies)
    assert avg_latency < 50.0, f"Average query latency {avg_latency:.2f}ms exceeded 50ms limit"


def test_configuration_driven_provider_selection(monkeypatch):
    """Verify EmbeddingService dynamically selects provider based on settings."""
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    svc_fast = EmbeddingService()
    assert isinstance(svc_fast.provider, FastEmbedProvider)

    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "tfidf")
    svc_tfidf = EmbeddingService()
    assert isinstance(svc_tfidf.provider, TFIDFEmbeddingProvider)

    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "mock")
    svc_mock = EmbeddingService()
    assert isinstance(svc_mock.provider, MockEmbeddingProvider)


def test_vector_dimension_mismatch_prevention(tmp_path: Path):
    """
    Ensure dimension mismatch between indexed vectors and query vector raises
    EmbeddingDimensionMismatchError and prevents silent failure.
    """
    store = VectorStore(storage_dir=tmp_path)

    # Store 384-dim vectors
    fast_provider = FastEmbedProvider()
    chunks = [
        DocumentChunk(
            chunk_id="c1",
            document_id="doc_dim_test",
            document_name="doc.pdf",
            page_number=1,
            section="General",
            text="General terms and conditions."
        )
    ]
    vecs_384 = fast_provider.embed_texts([c.text for c in chunks])
    store.add_document("doc_dim_test", chunks, vecs_384)

    # Query with mock provider (128-dim)
    mock_provider = MockEmbeddingProvider(dimension=128)
    q_vec_128 = mock_provider.embed_query("terms and conditions")

    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        store.search("doc_dim_test", q_vec_128)

    assert exc_info.value.query_dim == 128
    assert exc_info.value.store_dim == 384
    assert "Dimension mismatch for document 'doc_dim_test'" in str(exc_info.value)


def test_persisted_dense_vectors_across_restarts(tmp_path: Path):
    """
    Ensure dense vectors persisted to disk reload identically into a new VectorStore instance.
    """
    fast_provider = FastEmbedProvider()
    chunks = [
        DocumentChunk(
            chunk_id="c_restart_1",
            document_id="doc_restart",
            document_name="restart.pdf",
            page_number=1,
            section="Section 1",
            text="Notice shall be given in writing."
        )
    ]
    vecs = fast_provider.embed_texts([c.text for c in chunks])

    # Instance 1: add and save
    store1 = VectorStore(storage_dir=tmp_path)
    store1.add_document("doc_restart", chunks, vecs)
    saved_vecs = np.load(str(tmp_path / "doc_restart_vectors.npy"))
    assert saved_vecs.shape == (1, 384)

    # Instance 2: reload from disk
    store2 = VectorStore(storage_dir=tmp_path)
    assert store2.has_document("doc_restart")
    assert "doc_restart" in store2.vectors_by_doc
    assert store2.vectors_by_doc["doc_restart"].shape == (1, 384)
    np.testing.assert_allclose(store1.vectors_by_doc["doc_restart"], store2.vectors_by_doc["doc_restart"])

    # Query reloaded store
    retrieval2 = RetrievalService(EmbeddingService(), store2)
    retrieval2.embedding_service.provider = fast_provider
    res = retrieval2.retrieve("doc_restart", "written notice requirement", top_k=1, threshold=0.0)
    assert len(res) == 1
    assert res[0][0].chunk_id == "c_restart_1"


def test_document_ingestion_and_retrieval_end_to_end_with_dense(tmp_path: Path, monkeypatch):
    """
    Verify complete ingestion via DocumentService using FastEmbed, metadata tracking,
    and subsequent retrieval consistency.
    """
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    upload_dir = tmp_path / "uploads"
    vector_dir = tmp_path / "vectors"
    upload_dir.mkdir(parents=True)
    vector_dir.mkdir(parents=True)

    pdf_service = PDFService()
    chunking_service = ChunkingService(chunk_size=500, chunk_overlap=100, min_chunk_size=50)
    embedding_service = EmbeddingService()
    vector_store = VectorStore(storage_dir=vector_dir)

    doc_service = DocumentService(
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        embedding_service=embedding_service,
        vector_store=vector_store,
        upload_dir=upload_dir
    )

    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    meta = doc_service.process_document(contract_bytes, "synthetic_contract.pdf")

    assert meta.embedding_provider == "fastembed"
    assert meta.embedding_model == "BAAI/bge-small-en-v1.5"
    assert vector_store.has_document(meta.document_id)
    assert vector_store.vectors_by_doc[meta.document_id].shape[1] == 384

    # Query retrieval
    retrieval = RetrievalService(embedding_service, vector_store)
    results = retrieval.retrieve(meta.document_id, "How to cancel the contract?", top_k=2, threshold=0.1)
    assert len(results) > 0
    assert any("Termination" in r[0].section for r in results)


def test_api_chat_dimension_mismatch_http_400(monkeypatch, tmp_path: Path):
    """
    Verify that an API chat request encountering a vector dimension mismatch
    returns HTTP 400 with X-Error-Category header instead of crashing with HTTP 500.
    """
    with TestClient(app) as client:
        # Upload standard synthetic contract with whatever provider app initialized with
        contract_path = Path("documents/synthetic_contract.pdf")
        with open(contract_path, "rb") as f:
            upload_resp = client.post(
                "/api/documents/upload",
                files={"file": ("test_mismatch.pdf", f, "application/pdf")}
            )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["data"]["document_id"]

        from app.main import app_state
        original_provider = app_state["embedding_service"].provider

        try:
            # Inject a mismatching query embedding provider (dimension 64)
            app_state["embedding_service"].provider = MockEmbeddingProvider(dimension=64)

            chat_resp = client.post(
                "/api/chat",
                json={
                    "document_id": doc_id,
                    "question": "What is the termination clause?"
                }
            )
            assert chat_resp.status_code == 400
            assert "embedding_dimension_mismatch" in chat_resp.headers.get("X-Error-Category", "")
            assert "Dimension mismatch" in chat_resp.json()["detail"]
        finally:
            app_state["embedding_service"].provider = original_provider
            client.delete(f"/api/documents/{doc_id}")


def test_persisted_vector_rejection_on_dimension_incompatibility(tmp_path: Path):
    """
    Fix 1 Test: When persisted vectors on disk have a dimension that does not match
    the saved compatibility metadata (e.g. corrupted file or manual edit),
    VectorStore skips loading it instead of silently loading corrupted data.
    """
    import json
    chunks = [
        DocumentChunk(
            chunk_id="c_corrupt",
            document_id="doc_corrupt",
            document_name="corrupt.pdf",
            page_number=1,
            section="Section 1",
            text="Valid text passage."
        )
    ]
    # Save 128-dim vectors
    mock_128 = MockEmbeddingProvider(dimension=128)
    vecs_128 = mock_128.embed_texts([c.text for c in chunks])

    store = VectorStore(storage_dir=tmp_path)
    store.add_document("doc_corrupt", chunks, vecs_128)

    # Tamper with index metadata to declare 384 dimension
    meta_path = tmp_path / "doc_corrupt_meta.json"
    with open(meta_path, "w", encoding="utf-8") as mf:
        json.dump({
            "document_id": "doc_corrupt",
            "embedding_provider": "fastembed",
            "embedding_model": "BAAI/bge-small-en-v1.5",
            "dimension": 384,
            "chunk_count": 1
        }, mf)

    # Re-instantiate VectorStore; corrupted document must be skipped
    reloaded_store = VectorStore(storage_dir=tmp_path)
    assert not reloaded_store.has_document("doc_corrupt")
    assert "doc_corrupt" not in reloaded_store.vectors_by_doc


def test_duplicate_reuse_after_embedding_provider_model_change(tmp_path: Path):
    """
    Fix 2 Test: When a duplicate file is re-uploaded but the active embedding configuration
    has changed (e.g. from mock/tfidf to fastembed), DocumentService rebuilds/re-indexes
    the document under the new provider rather than returning stale vectors.
    """
    upload_dir = tmp_path / "uploads"
    vector_dir = tmp_path / "vectors"
    upload_dir.mkdir(parents=True)
    vector_dir.mkdir(parents=True)

    pdf_service = PDFService()
    chunking_service = ChunkingService(chunk_size=500, chunk_overlap=100, min_chunk_size=50)

    # Phase 1: Ingest document using MockEmbeddingProvider (128-dim)
    emb_service1 = EmbeddingService()
    emb_service1.provider = MockEmbeddingProvider(dimension=128)
    vector_store = VectorStore(storage_dir=vector_dir)

    doc_service = DocumentService(
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        embedding_service=emb_service1,
        vector_store=vector_store
    )
    doc_service.upload_dir = upload_dir
    doc_service.metadata_file = upload_dir / "documents_meta.json"

    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    doc1 = doc_service.process_document(contract_bytes, "contract.pdf")

    assert doc1.embedding_provider == "mock"
    assert vector_store.vectors_by_doc[doc1.document_id].shape[1] == 128

    # Phase 2: Switch embedding provider to FastEmbed (384-dim)
    emb_service2 = EmbeddingService()
    emb_service2.provider = FastEmbedProvider()
    doc_service.embedding_service = emb_service2

    # Process identical bytes under new provider; must detect config mismatch, rebuild, and not return stale 128-dim vectors
    doc2 = doc_service.process_document(contract_bytes, "contract_second_upload.pdf")

    assert doc2.embedding_provider == "fastembed"
    assert doc2.embedding_model == "BAAI/bge-small-en-v1.5"
    assert vector_store.has_document(doc2.document_id)
    assert vector_store.vectors_by_doc[doc2.document_id].shape[1] == 384


def test_dense_document_scoped_isolation(tmp_path: Path):
    """
    Fix 4 Test: Dense vectors from Document A never leak into Document B retrieval queries.
    """
    store = VectorStore(storage_dir=tmp_path)
    fast_provider = FastEmbedProvider()
    emb_service = EmbeddingService()
    emb_service.provider = fast_provider

    chunks_a = [
        DocumentChunk(
            chunk_id="chunk_a",
            document_id="doc_alpha",
            document_name="contract_alpha.pdf",
            page_number=1,
            section="Termination",
            text="Party Alpha may cancel or terminate this agreement within 10 days."
        )
    ]
    chunks_b = [
        DocumentChunk(
            chunk_id="chunk_b",
            document_id="doc_beta",
            document_name="contract_beta.pdf",
            page_number=1,
            section="Termination",
            text="Party Beta termination requires 90 days prior written notice."
        )
    ]

    store.add_document("doc_alpha", chunks_a, fast_provider.embed_texts([c.text for c in chunks_a]))
    store.add_document("doc_beta", chunks_b, fast_provider.embed_texts([c.text for c in chunks_b]))

    retrieval = RetrievalService(emb_service, store)

    # Scoped search in doc_alpha must never return chunk_b
    results_alpha = retrieval.retrieve("doc_alpha", "cancel agreement notice period", top_k=5, threshold=0.0)
    assert len(results_alpha) == 1
    assert results_alpha[0][0].document_id == "doc_alpha"
    assert results_alpha[0][0].chunk_id == "chunk_a"

    # Scoped search in doc_beta must never return chunk_a
    results_beta = retrieval.retrieve("doc_beta", "cancel agreement notice period", top_k=5, threshold=0.0)
    assert len(results_beta) == 1
    assert results_beta[0][0].document_id == "doc_beta"
    assert results_beta[0][0].chunk_id == "chunk_b"


def test_stale_persisted_vector_handling_on_search(tmp_path: Path):
    """
    Fix 4 Test: When VectorStore has a document indexed with 128-dim vectors,
    and a query comes in with 384-dim dense vectors, search raises EmbeddingDimensionMismatchError.
    """
    store = VectorStore(storage_dir=tmp_path)
    mock_provider = MockEmbeddingProvider(dimension=128)
    fast_provider = FastEmbedProvider()

    chunks = [
        DocumentChunk(
            chunk_id="c_stale",
            document_id="doc_stale",
            document_name="stale.pdf",
            page_number=1,
            section="General",
            text="Stale document text indexed under older provider."
        )
    ]
    vecs_stale = mock_provider.embed_texts([c.text for c in chunks])
    store.add_document("doc_stale", chunks, vecs_stale)

    # Query with FastEmbed dense vector (384-dim)
    q_vec_dense = fast_provider.embed_query("any search query")

    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        store.search("doc_stale", q_vec_dense)

    assert exc_info.value.query_dim == 384
    assert exc_info.value.store_dim == 128


def test_fastembed_cold_start_latency_measurement():
    """
    Fix 5 Test: Deterministic cold-start initialization and inference measurement.
    Ensures newly instantiated provider completes query embedding within bounded time.
    """
    t_start = time.perf_counter()
    cold_provider = FastEmbedProvider(model_name="BAAI/bge-small-en-v1.5")
    q_vec = cold_provider.embed_query("Initial cold query")
    elapsed_ms = (time.perf_counter() - t_start) * 1000.0

    assert isinstance(q_vec, np.ndarray)
    assert q_vec.shape == (1, 384)
    # Cold initialization (when model is cached on disk) should complete within 3000ms
    assert elapsed_ms < 3000.0, f"Cold start latency {elapsed_ms:.2f}ms exceeded limit"

