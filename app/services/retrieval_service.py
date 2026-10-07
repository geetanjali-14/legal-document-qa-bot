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

    def retrieve(
        self,
        document_id: str,
        query: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Embed query and retrieve top matching document chunks with similarity scores.
        """
        k = top_k or settings.TOP_K
        sim_threshold = threshold if threshold is not None else settings.SIMILARITY_THRESHOLD

        logger.info(f"Retrieving for doc={document_id}, query='{query[:50]}...', top_k={k}")
        query_vector = self.embedding_service.embed_query(query)

        results = self.vector_store.search(
            document_id=document_id,
            query_vector=query_vector,
            top_k=k,
            similarity_threshold=sim_threshold
        )

        logger.info(f"Retrieved {len(results)} chunks above threshold {sim_threshold}")
        return results
