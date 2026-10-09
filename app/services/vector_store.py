import json
import uuid
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.models.document import DocumentChunk
from app.core.config import settings
from app.core.logging import logger
from app.core.errors import EmbeddingDimensionMismatchError


class VectorStore:
    """
    Production-grade vector store backed by Neon pgvector / relational DB persistence,
    with local embedded Qdrant and memory cache for low-latency retrieval.
    Provides document isolation, deterministic chunk IDs, and safe recovery.
    """
    def __init__(self, storage_dir: Optional[Path] = None, repository: Optional[object] = None):
        self.storage_dir = storage_dir or settings.VECTOR_STORE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.repository = repository

        # Local embedded Qdrant DB directory (disposable fast cache)
        self.qdrant_dir = self.storage_dir / "qdrant_db"
        self.qdrant_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.qdrant_client = QdrantClient(path=str(self.qdrant_dir))
            logger.info(f"Initialized local embedded Qdrant client at {self.qdrant_dir}")
        except Exception as e:
            logger.warning(f"Failed to initialize file-based Qdrant, falling back to memory: {e}")
            self.qdrant_client = QdrantClient(":memory:")

        # In-memory document stores: doc_id -> chunks, doc_id -> embeddings matrix
        self.chunks_by_doc: Dict[str, List[DocumentChunk]] = {}
        self.vectors_by_doc: Dict[str, np.ndarray] = {}
        self._load_all_persisted()

    def set_repository(self, repository: object) -> None:
        """Dynamically attach database repository and reload any persisted DB chunks."""
        self.repository = repository
        self._load_from_repository()

    def _get_collection_name(self, document_id: str) -> str:
        # Qdrant collection name sanitized
        clean_id = document_id.replace("-", "_").lower()
        return f"doc_{clean_id}"

    def _get_doc_vector_path(self, document_id: str) -> Path:
        return self.storage_dir / f"{document_id}_vectors.npy"

    def _get_doc_chunks_path(self, document_id: str) -> Path:
        return self.storage_dir / f"{document_id}_chunks.json"

    def _get_doc_meta_path(self, document_id: str) -> Path:
        return self.storage_dir / f"{document_id}_meta.json"

    def _load_all_persisted(self) -> None:
        """Scan vector store directory and database to restore saved documents on startup."""
        # 1. Load from DB repository if configured
        self._load_from_repository()

        # 2. Check local disk files for any additional/fallback cached items
        for chunks_path in self.storage_dir.glob("*_chunks.json"):
            doc_id = chunks_path.stem.replace("_chunks", "")
            if doc_id in self.chunks_by_doc:
                continue
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
                    self._sync_to_qdrant(doc_id, chunks, vectors)
                    logger.info(f"Loaded persisted vector store from disk for doc {doc_id} ({len(chunks)} chunks)")
                except Exception as e:
                    logger.error(f"Error loading persisted vectors for {doc_id}: {str(e)}")

    def _load_from_repository(self) -> None:
        """Load stored chunks and vectors from Neon DB repository into memory and Qdrant cache."""
        if not self.repository:
            return
        try:
            doc_records = self.repository.list_document_records()
            for doc_rec in doc_records:
                doc_id = doc_rec.document_id
                if doc_id in self.chunks_by_doc:
                    continue
                db_chunks = self.repository.get_document_chunks(doc_id)
                if not db_chunks:
                    continue

                chunk_objs = []
                vec_list = []
                for c in db_chunks:
                    chunk_objs.append(
                        DocumentChunk(
                            chunk_id=c.chunk_id,
                            document_id=c.document_id,
                            document_name=doc_rec.original_filename or "",
                            page_number=c.page_number,
                            section=c.section,
                            section_number=c.section_number,
                            section_title=c.section_title,
                            clause_number=c.clause_number,
                            paragraph_number=c.paragraph_number,
                            parent_chunk_id=c.parent_chunk_id,
                            text=c.text,
                            token_count=c.token_count,
                            content_hash=c.content_hash,
                            breadcrumbs=c.breadcrumbs or []
                        )
                    )
                    raw_vec = c.embedding
                    # Handle both list and pgvector Vector object
                    vec_list.append(list(raw_vec) if hasattr(raw_vec, "__iter__") else raw_vec)

                if chunk_objs and vec_list:
                    vectors_arr = np.array(vec_list, dtype=np.float32)
                    self.chunks_by_doc[doc_id] = chunk_objs
                    self.vectors_by_doc[doc_id] = vectors_arr
                    self._sync_to_qdrant(doc_id, chunk_objs, vectors_arr)
                    logger.info(f"Loaded {len(chunk_objs)} chunks for doc {doc_id} directly from database repository into memory/Qdrant cache.")
        except Exception as repo_err:
            logger.warning(f"Could not load vector chunks from database repository: {repo_err}")

    def _sync_to_qdrant(self, document_id: str, chunks: List[DocumentChunk], normalized_vectors: np.ndarray) -> None:
        """Syncs document vectors and payload metadata into local Qdrant collection."""
        try:
            col_name = self._get_collection_name(document_id)
            dim = int(normalized_vectors.shape[1])
            # Recreate or ensure collection
            existing_cols = [c.name for c in self.qdrant_client.get_collections().collections]
            if col_name in existing_cols:
                self.qdrant_client.delete_collection(col_name)

            self.qdrant_client.create_collection(
                collection_name=col_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
            )

            points = []
            for idx, (chunk, vec) in enumerate(zip(chunks, normalized_vectors)):
                deterministic_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}_{chunk.chunk_id or idx}"))
                payload = {
                    "document_id": document_id,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": idx,
                    "page_number": chunk.page_number,
                    "section_title": chunk.section,
                    "section_number": getattr(chunk, "section_number", None),
                    "clause_number": getattr(chunk, "clause_number", None),
                    "text": chunk.text,
                }
                points.append(
                    PointStruct(
                        id=deterministic_uuid,
                        vector=vec.tolist(),
                        payload=payload
                    )
                )

            self.qdrant_client.upsert(
                collection_name=col_name,
                points=points
            )
        except Exception as e:
            logger.warning(f"Qdrant sync for doc {document_id} warning: {e}")

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
        """Store chunk vectors, compatibility metadata, Qdrant collection, and serialize to disk."""
        if len(chunks) != len(embeddings):
            raise ValueError(f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} vectors.")

        # Normalize vectors for cosine similarity (dot product of L2 normalized vectors)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized_vectors = embeddings / norms

        self.chunks_by_doc[document_id] = chunks
        self.vectors_by_doc[document_id] = normalized_vectors

        # Sync to Qdrant collection
        self._sync_to_qdrant(document_id, chunks, normalized_vectors)

        # Persist vectors and chunks to database repository if available
        if self.repository and hasattr(self.repository, "save_document_chunks"):
            try:
                self.repository.save_document_chunks(document_id, chunks, normalized_vectors)
                logger.info(f"Persisted {len(chunks)} chunks and vectors to database repository for {document_id}")
            except Exception as dberr:
                logger.warning(f"Failed to persist chunks to database repository for {document_id}: {dberr}")

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

        logger.info(f"Stored {len(chunks)} chunks and vectors for document {document_id} in Qdrant [provider={prov}, model={mod}, dim={normalized_vectors.shape[1]}]")

    def delete_document(self, document_id: str) -> bool:
        """Remove document from memory, disk, database, and Qdrant."""
        removed = False
        if document_id in self.chunks_by_doc:
            del self.chunks_by_doc[document_id]
            removed = True
        if document_id in self.vectors_by_doc:
            del self.vectors_by_doc[document_id]
            removed = True

        if self.repository and hasattr(self.repository, "delete_document_chunks"):
            try:
                self.repository.delete_document_chunks(document_id)
            except Exception as dberr:
                logger.warning(f"Failed to delete chunks from database repository for {document_id}: {dberr}")

        try:
            col_name = self._get_collection_name(document_id)
            # Defensively ensure Qdrant meta.json exists (in case data was wiped externally while running)
            if (self.qdrant_dir / "meta.json").exists():
                existing_cols = [c.name for c in self.qdrant_client.get_collections().collections]
                if col_name in existing_cols:
                    self.qdrant_client.delete_collection(col_name)
        except FileNotFoundError:
            # Underlying storage directory was wiped externally while running; safe to ignore
            pass
        except Exception as q_err:
            logger.warning(f"Could not delete Qdrant collection for {document_id}: {q_err}")

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
        Queries local Qdrant collection, falling back to local normalized dot product.
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

        # Try Qdrant retrieval first
        try:
            col_name = self._get_collection_name(document_id)
            res = self.qdrant_client.query_points(
                collection_name=col_name,
                query=normalized_q.flatten().tolist(),
                limit=top_k,
                score_threshold=similarity_threshold
            )
            qdrant_results = []
            chunk_by_id = {c.chunk_id: c for c in chunks}
            for pt in res.points:
                c_id = pt.payload.get("chunk_id")
                idx = pt.payload.get("chunk_index")
                chunk_obj = chunk_by_id.get(c_id) or (chunks[idx] if idx is not None and idx < len(chunks) else None)
                if chunk_obj:
                    qdrant_results.append((chunk_obj, float(pt.score)))
            if qdrant_results:
                return qdrant_results
        except Exception as q_err:
            logger.debug(f"Qdrant search fallback to dot product: {q_err}")

        # Fallback to in-memory cosine similarity
        similarities = np.dot(doc_vectors, normalized_q.T).flatten()
        sorted_indices = np.argsort(similarities)[::-1]

        results: List[Tuple[DocumentChunk, float]] = []
        for idx in sorted_indices[:top_k]:
            sim = float(similarities[idx])
            if sim >= similarity_threshold:
                results.append((chunks[idx], sim))

        return results
