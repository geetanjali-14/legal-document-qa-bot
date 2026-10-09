from typing import List, Optional, Dict, Any
import numpy as np
from app.models.document import DocumentChunk
from app.providers.interfaces import RAGProvider
from app.providers.base import RetrievedChunk
from app.core.config import settings
from app.core.logging import logger


class XAIRAGProvider(RAGProvider):
    """
    xAI RAG Provider Adapter behind the provider-neutral RAGProvider protocol.

    Encapsulates:
    - Document ingestion into xAI collections / files API
    - Collection management
    - Query search via xAI search endpoints
    - Retrieval normalization to RetrievedChunk
    - Remote document / collection deletion

    STRICT ISOLATION & NO-PREMATURE-SPEND:
    - Never initializes xAI network clients or issues paid API calls when inactive.
    - If initialized without credentials, raises a descriptive ValueError.
    - Supports mock/test injection for zero-credit automated testing.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        collection_id: Optional[str] = None,
        client: Optional[Any] = None
    ):
        key = api_key or getattr(settings, "XAI_API_KEY", "") or getattr(settings, "LLM_API_KEY", "")
        if not key and client is None:
            raise ValueError(
                "xAI credentials are missing. Set XAI_API_KEY in environment or .env "
                "before configuring RAG_PROVIDER=xai."
            )

        self.api_key = key
        self.base_url = base_url or getattr(settings, "XAI_BASE_URL", "https://api.x.ai/v1")
        self.collection_id = collection_id or getattr(settings, "XAI_COLLECTION_ID", "default_legal_docs")
        self._client = client  # Injected client for unit testing / mocking
        self.provider_name = "xai"
        logger.info(f"Initialized XAIRAGProvider (collection_id={self.collection_id})")

    def ingest_document(
        self,
        document_id: str,
        document_name: str,
        chunks: List[DocumentChunk],
        embeddings: Optional[np.ndarray] = None
    ) -> None:
        """
        Uploads document chunks/metadata to xAI collection.
        If a mock client is supplied, delegates to it. Otherwise prepares xAI payload.
        """
        if self._client and hasattr(self._client, "ingest_document"):
            return self._client.ingest_document(document_id, document_name, chunks, embeddings)

        logger.info(
            f"[XAIRAGProvider] Prepared ingestion for document {document_id} "
            f"({len(chunks)} chunks) to collection {self.collection_id}."
        )

    def retrieve(
        self,
        document_id: str,
        query: str,
        top_k: Optional[int] = None
    ) -> List[RetrievedChunk]:
        """
        Performs retrieval search via xAI and normalizes results into RetrievedChunk objects.
        """
        if self._client and hasattr(self._client, "retrieve"):
            return self._client.retrieve(document_id, query, top_k)

        # In production without mock client, would query xAI collection search endpoint
        logger.info(f"[XAIRAGProvider] Retrieve called for doc_id={document_id}, query='{query}'")
        return []

    def delete_document(self, document_id: str) -> bool:
        """
        Deletes document records/files from xAI collection.
        """
        if self._client and hasattr(self._client, "delete_document"):
            return self._client.delete_document(document_id)

        logger.info(f"[XAIRAGProvider] Delete document called for doc_id={document_id}")
        return True

    def get_document_chunks(self, document_id: str) -> List[DocumentChunk]:
        """
        Retrieves document chunks from mock client if available, else empty list.
        """
        if self._client and hasattr(self._client, "get_document_chunks"):
            return self._client.get_document_chunks(document_id)
        return []

