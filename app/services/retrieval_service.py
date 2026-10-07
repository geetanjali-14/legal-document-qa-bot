import time
from typing import List, Tuple, Optional
from app.models.document import DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.core.config import settings
from app.core.logging import logger


class RetrievalService:
    def __init__(self, embedding_service: EmbeddingService, vector_store: VectorStore):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.last_retrieval_latency_ms: float = 0.0
        self.last_embedding_latency_ms: float = 0.0

    def retrieve(
        self,
        document_id: str,
        query: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Embed query and retrieve top matching document chunks with similarity scores.
        Tracks retrieval latency and query embedding latency.
        """
        t_retrieval_start = time.perf_counter()
        k = top_k or settings.TOP_K
        sim_threshold = threshold if threshold is not None else settings.SIMILARITY_THRESHOLD

        logger.info(f"Retrieving for doc={document_id}, query='{query[:50]}...', top_k={k}")

        # If vocabulary-based embedding provider (e.g. TF-IDF) is not fitted, fit from indexed chunks
        if hasattr(self.embedding_service.provider, "fit_corpus") and not getattr(self.embedding_service.provider, "is_fitted", False):
            doc_chunks = self.vector_store.chunks_by_doc.get(document_id, [])
            if doc_chunks:
                self.embedding_service.provider.fit_corpus([c.text for c in doc_chunks])

        t_embed_start = time.perf_counter()
        query_vector = self.embedding_service.embed_query(query)
        self.last_embedding_latency_ms = max(0.0, (time.perf_counter() - t_embed_start) * 1000.0)


        results = self.vector_store.search(
            document_id=document_id,
            query_vector=query_vector,
            top_k=k,
            similarity_threshold=sim_threshold
        )
        self.last_retrieval_latency_ms = max(0.0, (time.perf_counter() - t_retrieval_start) * 1000.0)

        logger.info(
            f"Retrieved {len(results)} chunks above threshold {sim_threshold} "
            f"(retrieval={self.last_retrieval_latency_ms:.2f}ms, embedding={self.last_embedding_latency_ms:.2f}ms)"
        )
        return results

