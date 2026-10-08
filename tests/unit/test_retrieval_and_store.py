import numpy as np
from pathlib import Path
from app.services.vector_store import VectorStore
from app.services.retrieval_service import RetrievalService
from app.services.embedding_service import MockEmbeddingProvider, EmbeddingService, TFIDFEmbeddingProvider
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


def test_tfidf_retrieval_finds_inflected_holdover_clause(tmp_path: Path):
    store = VectorStore(storage_dir=tmp_path)
    embedding_service = EmbeddingService()
    embedding_service.provider = TFIDFEmbeddingProvider()
    document_id = "doc_rental"
    chunks = [
        DocumentChunk(
            chunk_id="rental_intro",
            document_id=document_id,
            document_name="rental.pdf",
            page_number=1,
            section="Rental Agreement",
            text="This rental agreement is made between the owner and tenant for residential purposes.",
        ),
        DocumentChunk(
            chunk_id="rental_parties",
            document_id=document_id,
            document_name="rental.pdf",
            page_number=2,
            section="General Terms",
            text="The parties have signed this agreement. The tenant will follow the rules of the premises.",
        ),
        DocumentChunk(
            chunk_id="rental_holdover",
            document_id=document_id,
            document_name="rental.pdf",
            page_number=3,
            section="Holdover Damages",
            text=(
                "If the premises are not vacated by the tenant at termination of the rent period, "
                "the tenant will pay damages at two times the rent for occupation commencing from expiry."
            ),
        ),
    ]
    vectors = embedding_service.embed_texts([chunk.text for chunk in chunks], document_id=document_id)
    store.add_document(document_id, chunks, vectors, embedding_provider="tfidf", embedding_model="tfidf-scikit")
    retrieval = RetrievalService(embedding_service, store)

    results = retrieval.retrieve(
        document_id=document_id,
        query="What happens if the tenant does not vacate after the agreement expires?",
        top_k=4,
    )

    assert results
    assert any(chunk.chunk_id == "rental_holdover" for chunk, _ in results)
