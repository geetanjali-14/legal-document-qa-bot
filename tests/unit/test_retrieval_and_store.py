import numpy as np
from pathlib import Path
from app.services.vector_store import VectorStore
from app.services.retrieval_service import RetrievalService
from app.services.embedding_service import MockEmbeddingProvider, EmbeddingService
from app.models.document import DocumentChunk


def test_vector_store_isolation_and_retrieval(tmp_path: Path):
    store = VectorStore(storage_dir=tmp_path)
    embedding_service = EmbeddingService()
    embedding_service.provider = MockEmbeddingProvider(dimension=16)

    chunks_doc1 = [
        DocumentChunk(
            chunk_id="c1",
            document_id="doc_a",
            document_name="contract_a.pdf",
            page_number=1,
            section="Termination",
            text="Termination requires thirty days notice."
        )
    ]
    vecs_doc1 = embedding_service.embed_texts([c.text for c in chunks_doc1])
    store.add_document("doc_a", chunks_doc1, vecs_doc1)

    chunks_doc2 = [
        DocumentChunk(
            chunk_id="c2",
            document_id="doc_b",
            document_name="lease_b.pdf",
            page_number=4,
            section="Rent",
            text="Monthly rent is five thousand dollars."
        )
    ]
    vecs_doc2 = embedding_service.embed_texts([c.text for c in chunks_doc2])
    store.add_document("doc_b", chunks_doc2, vecs_doc2)

    retrieval = RetrievalService(embedding_service, store)

    # Scoped retrieval to doc_a must NEVER return chunks from doc_b
    results_a = retrieval.retrieve("doc_a", "notice period for termination", top_k=2, threshold=0.0)
    assert len(results_a) == 1
    assert results_a[0][0].document_id == "doc_a"
    assert results_a[0][0].chunk_id == "c1"

    # Search against doc_b for rent
    results_b = retrieval.retrieve("doc_b", "monthly rent amount", top_k=2, threshold=0.0)
    assert len(results_b) == 1
    assert results_b[0][0].document_id == "doc_b"
    assert results_b[0][0].chunk_id == "c2"

    # Delete doc_a and verify
    assert store.delete_document("doc_a") is True
    assert len(retrieval.retrieve("doc_a", "termination")) == 0
