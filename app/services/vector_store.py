import json
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import numpy as np
from app.models.document import DocumentChunk
from app.core.config import settings
from app.core.logging import logger
from app.core.errors import EmbeddingDimensionMismatchError


class VectorStore:
    """
    Production-grade local vector store with cosine similarity, metadata filtering,
    and persistent JSON/NPZ backing.
    """
    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or settings.VECTOR_STORE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # In-memory document stores: doc_id -> chunks, doc_id -> embeddings matrix
        self.chunks_by_doc: Dict[str, List[DocumentChunk]] = {}
        self.vectors_by_doc: Dict[str, np.ndarray] = {}
        self._load_all_persisted()

    def _get_doc_vector_path(self, document_id: str) -> Path:
        return self.storage_dir / f"{document_id}_vectors.npy"

    def _get_doc_chunks_path(self, document_id: str) -> Path:
        return self.storage_dir / f"{document_id}_chunks.json"

    def _get_doc_meta_path(self, document_id: str) -> Path:
        return self.storage_dir / f"{document_id}_meta.json"

    def _load_all_persisted(self) -> None:
        """Scan vector store directory and restore saved documents on startup."""
        for chunks_path in self.storage_dir.glob("*_chunks.json"):
            doc_id = chunks_path.stem.replace("_chunks", "")
            vector_path = self._get_doc_vector_path(doc_id)
            meta_path = self._get_doc_meta_path(doc_id)
            if vector_path.exists():
                try:
                    with open(chunks_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        chunks = [DocumentChunk(**item) for item in data]
                    vectors = np.load(str(vector_path))

                    # Validate vector compatibility metadata if present
                    if meta_path.exists():
                        try:
                            with open(meta_path, "r", encoding="utf-8") as mf:
                                index_meta = json.load(mf)
                            meta_dim = index_meta.get("dimension")
                            if meta_dim is not None and vectors.shape[1] != meta_dim:
                                logger.error(
                                    f"Persisted vector file corrupt for doc {doc_id}: "
                                    f"shape dimension {vectors.shape[1]} != meta dimension {meta_dim}. Skipping load."
                                )
                                continue
                        except Exception as m_err:
                            logger.warning(f"Error parsing index metadata for {doc_id}: {m_err}")

                    self.chunks_by_doc[doc_id] = chunks
                    self.vectors_by_doc[doc_id] = vectors
                    logger.info(f"Loaded persisted vector store for doc {doc_id} ({len(chunks)} chunks)")
                except Exception as e:
                    logger.error(f"Error loading persisted vectors for {doc_id}: {str(e)}")

    def get_index_metadata(self, document_id: str) -> Optional[Dict]:
        """Load persisted index metadata (provider, model, dimension) for document."""
        meta_path = self._get_doc_meta_path(document_id)
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error reading index metadata for {document_id}: {e}")
        return None

    def add_document(
        self,
        document_id: str,
        chunks: List[DocumentChunk],
        embeddings: np.ndarray,
        embedding_provider: Optional[str] = None,
        embedding_model: Optional[str] = None
    ) -> None:
        """Store chunk vectors, compatibility metadata, and serialize to disk."""
        if len(chunks) != len(embeddings):
            raise ValueError(f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} vectors.")

        # Normalize vectors for cosine similarity (dot product of L2 normalized vectors)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized_vectors = embeddings / norms

        self.chunks_by_doc[document_id] = chunks
        self.vectors_by_doc[document_id] = normalized_vectors

        # Persist vectors and chunks to disk
        np.save(str(self._get_doc_vector_path(document_id)), normalized_vectors)
        with open(self._get_doc_chunks_path(document_id), "w", encoding="utf-8") as f:
            json.dump([c.model_dump() for c in chunks], f, indent=2)

        # Persist index compatibility metadata
        prov = (embedding_provider or settings.EMBEDDING_PROVIDER).lower()
        mod = embedding_model or settings.EMBEDDING_MODEL
        index_meta = {
            "document_id": document_id,
            "embedding_provider": prov,
            "embedding_model": mod,
            "dimension": int(normalized_vectors.shape[1]),
            "chunk_count": len(chunks)
        }
        with open(self._get_doc_meta_path(document_id), "w", encoding="utf-8") as f:
            json.dump(index_meta, f, indent=2)

        logger.info(f"Stored {len(chunks)} chunks and vectors for document {document_id} [provider={prov}, model={mod}, dim={normalized_vectors.shape[1]}]")

    def delete_document(self, document_id: str) -> bool:
        """Remove document from memory and disk."""
        removed = False
        if document_id in self.chunks_by_doc:
            del self.chunks_by_doc[document_id]
            removed = True
        if document_id in self.vectors_by_doc:
            del self.vectors_by_doc[document_id]
            removed = True

        v_path = self._get_doc_vector_path(document_id)
        if v_path.exists():
            v_path.unlink()
            removed = True

        c_path = self._get_doc_chunks_path(document_id)
        if c_path.exists():
            c_path.unlink()
            removed = True

        m_path = self._get_doc_meta_path(document_id)
        if m_path.exists():
            m_path.unlink()
            removed = True

        return removed

    def has_document(self, document_id: str) -> bool:
        """Check if document has both indexed chunks and vectors in memory."""
        return (
            document_id in self.chunks_by_doc
            and document_id in self.vectors_by_doc
            and len(self.chunks_by_doc[document_id]) > 0
            and len(self.vectors_by_doc[document_id]) > 0
        )

    def search(

        self,
        document_id: str,
        query_vector: np.ndarray,
        top_k: int = 4,
        similarity_threshold: float = 0.1
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Execute cosine similarity search against chunks scoped specifically to document_id.
        Prevents accidental cross-document contamination.
        """
        if document_id not in self.vectors_by_doc or document_id not in self.chunks_by_doc:
            logger.warning(f"No vectors indexed for document_id {document_id}")
            return []

        doc_vectors = self.vectors_by_doc[document_id]
        chunks = self.chunks_by_doc[document_id]

        if len(chunks) == 0 or len(doc_vectors) == 0:
            return []

        # Ensure query vector dimension matches stored document vectors
        if query_vector.shape[1] != doc_vectors.shape[1]:
            err_msg = (
                f"Dimension mismatch for document '{document_id}': "
                f"query has dimension {query_vector.shape[1]}, but indexed store has dimension {doc_vectors.shape[1]}. "
                f"Ensure the same embedding model is configured as when the document was indexed."
            )
            logger.error(err_msg)
            raise EmbeddingDimensionMismatchError(
                message=err_msg,
                query_dim=query_vector.shape[1],
                store_dim=doc_vectors.shape[1]
            )

        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            q_norm = 1.0
        normalized_q = query_vector / q_norm

        # Cosine similarity is dot product
        similarities = np.dot(doc_vectors, normalized_q.T).flatten()

        # Sort indices descending
        sorted_indices = np.argsort(similarities)[::-1]

        results: List[Tuple[DocumentChunk, float]] = []
        for idx in sorted_indices[:top_k]:
            sim = float(similarities[idx])
            if sim >= similarity_threshold:
                results.append((chunks[idx], sim))

        return results
