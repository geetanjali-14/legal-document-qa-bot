from typing import Protocol, List, Optional, runtime_checkable
import numpy as np
from app.models.chat import Message
from app.models.document import DocumentChunk
from app.providers.base import RetrievedChunk, LLMResponse


@runtime_checkable
class RAGProvider(Protocol):
    """
    Provider-neutral RAG contract.
    Decouples document ingestion, query retrieval, and document deletion from underlying backends.
    """
    def ingest_document(
        self,
        document_id: str,
        document_name: str,
        chunks: List[DocumentChunk],
        embeddings: Optional[np.ndarray] = None
    ) -> None:
        """Index a document and its chunks into the RAG backend."""
        ...

    def retrieve(
        self,
        document_id: str,
        query: str,
        top_k: Optional[int] = None
    ) -> List[RetrievedChunk]:
        """Retrieve relevant chunks for a document query, returned as normalized RetrievedChunk objects."""
        ...

    def delete_document(self, document_id: str) -> bool:
        """Delete document points/data from the RAG store."""
        ...

    def get_document_chunks(self, document_id: str) -> List[DocumentChunk]:
        """Retrieve stored document chunks for a document, or empty list if unavailable."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """
    Provider-neutral LLM generation contract.
    Decouples prompt synthesis and completion generation from concrete model APIs.
    """
    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> LLMResponse:
        """Generate an answer using bounded context chunks and conversation history."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Provider-neutral text embedding contract.
    Decouples dense vector generation from concrete embedding models.
    """
    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        """Embed a list of text strings into an NxDim 2D numpy array."""
        ...

    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        """Embed a single query string into a 1xDim 2D numpy array."""
        ...

