from typing import List, Optional
import numpy as np
from app.models.document import DocumentChunk
from app.providers.interfaces import RAGProvider
from app.providers.base import RetrievedChunk
from app.services.retrieval_service import RetrievalService
from app.services.vector_store import VectorStore
from app.services.embedding_service import EmbeddingService
from app.core.logging import logger


class LocalRAGProvider(RAGProvider):
    """
    Wraps the existing, working local RAG implementation (Qdrant + BM25 + RRF)
    behind the provider-neutral RAGProvider protocol.

    Preserves 100% of existing behavior:
    - VectorStore Qdrant indexing and point persistence
    - BM25 reciprocal rank fusion (RRF)
    - Vocabulary isolation and content-word scoring
    - Exact DocumentChunk to RetrievedChunk mapping
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        vector_store: VectorStore,
        embedding_service: Optional[EmbeddingService] = None
    ):
        self.retrieval_service = retrieval_service
        self.vector_store = vector_store
        self.embedding_service = embedding_service or retrieval_service.embedding_service
        self.provider_name = "local"

    def ingest_document(
        self,
        document_id: str,
        document_name: str,
        chunks: List[DocumentChunk],
        embeddings: Optional[np.ndarray] = None
    ) -> None:
        """
        Store chunks and embeddings into local VectorStore (Qdrant + disk cache).
        If embeddings are not passed, generate them via embedding_service.
        """
        if embeddings is None and self.embedding_service is not None:
            chunk_texts = [c.text for c in chunks]
            embeddings = self.embedding_service.embed_texts(chunk_texts, document_id=document_id)

        actual_provider = getattr(self.embedding_service, "provider_name", "tfidf")
        actual_model = getattr(self.embedding_service, "model_name", "local")

        self.vector_store.add_document(
            document_id=document_id,
            chunks=chunks,
            embeddings=embeddings if embeddings is not None else np.empty((0, 0)),
            embedding_provider=actual_provider,
            embedding_model=actual_model
        )

        # Invalidate / prepare BM25 index for this document in retrieval service
        if hasattr(self.retrieval_service, "invalidate_bm25_cache"):
            self.retrieval_service.invalidate_bm25_cache(document_id)

        logger.info(
            f"[LocalRAGProvider] Ingested document {document_id} ({len(chunks)} chunks) into local vector store."
        )

    def retrieve(
        self,
        document_id: str,
        query: str,
        top_k: Optional[int] = None
    ) -> List[RetrievedChunk]:
        """
        Executes hybrid retrieval (BM25 + Qdrant RRF) through existing RetrievalService.
        Adapts (DocumentChunk, score) pairs into normalized RetrievedChunk objects.
        """
        raw_results = self.retrieval_service.retrieve(
            document_id=document_id,
            query=query,
            top_k=top_k
        )

        retrieved: List[RetrievedChunk] = []
        for chunk, score in raw_results:
            retrieved.append(
                RetrievedChunk(
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    score=float(score),
                    page_number=chunk.page_number,
                    section=chunk.section or "General",
                    section_number=chunk.section_number,
                    section_title=chunk.section_title,
                    clause_number=chunk.clause_number,
                    paragraph_number=chunk.paragraph_number,
                    document_name=chunk.document_name,
                    metadata={
                        "token_count": chunk.token_count,
                        "breadcrumbs": chunk.breadcrumbs,
                        "content_hash": chunk.content_hash,
                        "parent_chunk_id": chunk.parent_chunk_id
                    }
                )
            )

        return retrieved

    def delete_document(self, document_id: str) -> bool:
        """
        Deletes points and cached files for document from local vector store and retrieval cache.
        """
        if hasattr(self.retrieval_service, "delete_document_cache"):
            self.retrieval_service.delete_document_cache(document_id)

        return self.vector_store.delete_document(document_id)

    def get_document_chunks(self, document_id: str) -> List[DocumentChunk]:
        """
        Retrieves stored document chunks directly from the local vector store cache.
        """
        chunks_map = getattr(self.vector_store, "chunks_by_doc", None)
        if isinstance(chunks_map, dict):
            return list(chunks_map.get(document_id, []))
        return []

