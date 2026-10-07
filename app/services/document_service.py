import json
import uuid
import re
import time
import hashlib
from pathlib import Path
from typing import List, Optional, Dict
from app.models.document import DocumentMetadata, DocumentChunk
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.core.config import settings
from app.core.logging import logger
from app.core.errors import (
    ResourceLimitError,
    FileSizeLimitExceededError,
    ChunkLimitExceededError
)
from app.core.telemetry import (
    DocumentProcessingTelemetry,
    record_document_telemetry,
    pricing_registry
)


class DocumentService:
    def __init__(
        self,
        pdf_service: PDFService,
        chunking_service: ChunkingService,
        embedding_service: EmbeddingService,
        vector_store: VectorStore
    ):
        self.pdf_service = pdf_service
        self.chunking_service = chunking_service
        self.embedding_service = embedding_service
        self.vector_store = vector_store

        self.upload_dir = settings.UPLOAD_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.upload_dir / "documents_meta.json"
        self.documents: Dict[str, DocumentMetadata] = {}
        self._hash_to_id: Dict[str, str] = {}
        self._load_metadata()

    def _load_metadata(self) -> None:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    updated = False
                    for item in data:
                        meta = DocumentMetadata(**item)
                        # Backfill content_hash if missing from historical metadata
                        if not meta.content_hash:
                            saved_path = self.upload_dir / meta.filename
                            if saved_path.exists():
                                try:
                                    with open(saved_path, "rb") as f_bytes:
                                        meta.content_hash = hashlib.sha256(f_bytes.read()).hexdigest()
                                    updated = True
                                    logger.info(f"Backfilled content_hash for document {meta.document_id}")
                                except Exception as err:
                                    logger.warning(f"Could not backfill hash for {meta.document_id}: {err}")

                        self.documents[meta.document_id] = meta
                        if meta.content_hash:
                            self._hash_to_id[meta.content_hash] = meta.document_id

                    if updated:
                        self._save_metadata()

                logger.info(f"Loaded {len(self.documents)} document records from metadata store.")
            except Exception as e:
                logger.error(f"Failed to load document metadata: {e}")

    def _save_metadata(self) -> None:
        try:
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump([d.model_dump(mode="json") for d in self.documents.values()], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save document metadata: {e}")

    def sanitize_filename(self, filename: str) -> str:
        """Prevent path traversal and clean malicious filename characters."""
        clean = Path(filename).name  # Strips directory path
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', clean)
        return clean or "document.pdf"

    def find_by_content_hash(self, content_hash: str) -> Optional[DocumentMetadata]:
        """Look up existing document metadata by SHA-256 content hash."""
        doc_id = self._hash_to_id.get(content_hash)
        if doc_id and doc_id in self.documents:
            return self.documents[doc_id]
        for doc in self.documents.values():
            if doc.content_hash == content_hash:
                self._hash_to_id[content_hash] = doc.document_id
                return doc
        return None

    def process_document(self, file_bytes: bytes, original_filename: str) -> DocumentMetadata:
        """
        Validate, store, extract, chunk, embed, and index an uploaded document.
        Detects duplicates based on SHA-256 hash of raw bytes before any expensive processing.
        """
        # Validate file size
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise FileSizeLimitExceededError(
                f"File size ({len(file_bytes)} bytes) exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_MB}MB."
            )

        if not file_bytes.startswith(b"%PDF"):
            raise ValueError("Invalid file format. Only standard PDF documents are supported.")

        t_process_start = time.perf_counter()

        # Compute canonical content hash
        content_hash = hashlib.sha256(file_bytes).hexdigest()

        # Check for existing duplicate document by content hash
        existing_doc = self.find_by_content_hash(content_hash)
        if existing_doc:
            # Check for corrupt/inconsistent state: metadata exists but vector store data missing
            if not self.vector_store.has_document(existing_doc.document_id):
                raise RuntimeError(
                    f"Document {existing_doc.document_id} metadata exists with matching hash "
                    f"but vector data is unexpectedly missing or corrupted."
                )

            # Validate that existing document's indexed vectors match current embedding configuration
            current_provider = self.embedding_service.provider_name.lower()
            current_model = self.embedding_service.model_name
            index_meta = self.vector_store.get_index_metadata(existing_doc.document_id)

            existing_provider = (
                (index_meta.get("embedding_provider") if index_meta else None)
                or existing_doc.embedding_provider
                or ""
            ).lower()
            existing_model = (
                (index_meta.get("embedding_model") if index_meta else None)
                or existing_doc.embedding_model
                or ""
            )

            is_compatible = True
            if existing_provider and existing_provider != current_provider:
                is_compatible = False
            elif existing_model and existing_model != current_model:
                is_compatible = False

            if is_compatible:
                t_dup_end = time.perf_counter()
                total_latency_ms = max(0.0, (t_dup_end - t_process_start) * 1000.0)

                # Record duplicate detection telemetry (skipped work is NOT reported as completed)
                dup_telemetry = DocumentProcessingTelemetry(
                    event="document_duplicate_detected",
                    document_id=existing_doc.document_id,
                    filename=self.sanitize_filename(original_filename),
                    file_size_bytes=len(file_bytes),
                    page_count=existing_doc.page_count,
                    chunk_count=existing_doc.chunk_count,
                    extraction_latency_ms=0.0,
                    chunking_latency_ms=0.0,
                    embedding_latency_ms=0.0,
                    indexing_latency_ms=0.0,
                    total_latency_ms=round(total_latency_ms, 2),
                    embedding_provider=current_provider,
                    embedding_model=current_model,
                    embedding_tokens=None,
                    estimated_embedding_cost=None,
                    status="duplicate_reused",
                    is_duplicate=True,
                    content_hash=content_hash
                )
                record_document_telemetry(dup_telemetry)

                logger.info(
                    f"Duplicate document detected (hash={content_hash[:12]}..., file='{original_filename}'). "
                    f"Reusing existing document {existing_doc.document_id} in {total_latency_ms:.2f}ms."
                )
                return existing_doc
            else:
                logger.info(
                    f"Duplicate document found ({existing_doc.document_id}), but embedding configuration changed "
                    f"from provider='{existing_provider}', model='{existing_model}' to "
                    f"provider='{current_provider}', model='{current_model}'. "
                    f"Rebuilding index to prevent stale or incompatible vectors."
                )
                self.vector_store.delete_document(existing_doc.document_id)
                del self.documents[existing_doc.document_id]
                if content_hash in self._hash_to_id:
                    del self._hash_to_id[content_hash]

        # Document does not exist or requires re-indexing: proceed with standard ingestion
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        safe_name = f"{doc_id}_{self.sanitize_filename(original_filename)}"
        saved_path = self.upload_dir / safe_name

        with open(saved_path, "wb") as f:
            f.write(file_bytes)

        try:
            # 1. Extract text and pages
            t_extract_start = time.perf_counter()
            pages = self.pdf_service.extract_text_and_pages(saved_path)
            extract_latency_ms = max(0.0, (time.perf_counter() - t_extract_start) * 1000.0)

            # 2. Chunk text with section awareness
            t_chunk_start = time.perf_counter()
            chunks = self.chunking_service.chunk_document(
                document_id=doc_id,
                document_name=original_filename,
                pages=pages
            )
            chunk_latency_ms = max(0.0, (time.perf_counter() - t_chunk_start) * 1000.0)

            if not chunks:
                raise ValueError("No extractable chunks found in document.")

            if len(chunks) > settings.MAX_CHUNKS_PER_DOC:
                raise ChunkLimitExceededError(
                    f"Document generated {len(chunks)} chunks, exceeding max limit of {settings.MAX_CHUNKS_PER_DOC}."
                )

            # 3. Generate embeddings
            t_embed_start = time.perf_counter()
            chunk_texts = [c.text for c in chunks]
            embeddings = self.embedding_service.embed_texts(chunk_texts)
            embed_latency_ms = max(0.0, (time.perf_counter() - t_embed_start) * 1000.0)

            # 4. Store in vector database
            t_index_start = time.perf_counter()
            actual_provider = self.embedding_service.provider_name
            actual_model = self.embedding_service.model_name
            actual_dimension = int(embeddings.shape[1]) if embeddings.ndim > 1 else 0

            self.vector_store.add_document(
                doc_id,
                chunks,
                embeddings,
                embedding_provider=actual_provider,
                embedding_model=actual_model
            )
            index_latency_ms = max(0.0, (time.perf_counter() - t_index_start) * 1000.0)

            total_latency_ms = max(0.0, (time.perf_counter() - t_process_start) * 1000.0)

            meta = DocumentMetadata(
                document_id=doc_id,
                filename=safe_name,
                original_filename=original_filename,
                file_size_bytes=len(file_bytes),
                page_count=len(pages),
                chunk_count=len(chunks),
                content_hash=content_hash,
                embedding_provider=actual_provider,
                embedding_model=actual_model,
                embedding_dimension=actual_dimension,
                status="processed"
            )
            self.documents[doc_id] = meta
            self._hash_to_id[content_hash] = doc_id
            self._save_metadata()

            # Record document processing telemetry (safe metrics, no raw content)
            emb_tokens = getattr(self.embedding_service, "last_tokens", None)
            emb_cost = pricing_registry.calculate_cost(
                provider=settings.EMBEDDING_PROVIDER,
                model=settings.EMBEDDING_MODEL,
                input_tokens=emb_tokens,
                output_tokens=0
            )

            doc_telemetry = DocumentProcessingTelemetry(
                document_id=doc_id,
                filename=self.sanitize_filename(original_filename),
                file_size_bytes=len(file_bytes),
                page_count=len(pages),
                chunk_count=len(chunks),
                extraction_latency_ms=round(extract_latency_ms, 2),
                chunking_latency_ms=round(chunk_latency_ms, 2),
                embedding_latency_ms=round(embed_latency_ms, 2),
                indexing_latency_ms=round(index_latency_ms, 2),
                total_latency_ms=round(total_latency_ms, 2),
                embedding_provider=settings.EMBEDDING_PROVIDER,
                embedding_model=settings.EMBEDDING_MODEL,
                embedding_tokens=emb_tokens,
                estimated_embedding_cost=emb_cost,
                status="success",
                is_duplicate=False,
                content_hash=content_hash
            )
            record_document_telemetry(doc_telemetry)

            logger.info(
                f"Successfully processed document {original_filename} (ID: {doc_id}, hash={content_hash[:12]}...) "
                f"in {total_latency_ms:.2f}ms [pages={len(pages)}, chunks={len(chunks)}]"
            )
            return meta

        except Exception as e:
            # Clean up on failure
            if saved_path.exists():
                saved_path.unlink()
            self.vector_store.delete_document(doc_id)
            if doc_id in self.documents:
                del self.documents[doc_id]
            if content_hash in self._hash_to_id:
                del self._hash_to_id[content_hash]

            # Record failure / rejection telemetry
            t_err_end = time.perf_counter()
            err_latency_ms = max(0.0, (t_err_end - t_process_start) * 1000.0)
            err_cat = getattr(e, "error_category", None)
            fail_status = "rejected" if isinstance(e, ResourceLimitError) else "failed"

            err_telemetry = DocumentProcessingTelemetry(
                document_id=doc_id,
                filename=self.sanitize_filename(original_filename),
                file_size_bytes=len(file_bytes),
                page_count=0,
                chunk_count=0,
                extraction_latency_ms=0.0,
                chunking_latency_ms=0.0,
                embedding_latency_ms=0.0,
                indexing_latency_ms=0.0,
                total_latency_ms=round(err_latency_ms, 2),
                embedding_provider=settings.EMBEDDING_PROVIDER,
                embedding_model=settings.EMBEDDING_MODEL,
                status=fail_status,
                error_category=err_cat,
                is_duplicate=False,
                content_hash=content_hash
            )
            record_document_telemetry(err_telemetry)

            raise e

    def list_documents(self) -> List[DocumentMetadata]:
        return list(self.documents.values())

    def get_document(self, document_id: str) -> Optional[DocumentMetadata]:
        return self.documents.get(document_id)

    def delete_document(self, document_id: str) -> bool:
        if document_id not in self.documents:
            return False

        meta = self.documents[document_id]
        if meta.content_hash and meta.content_hash in self._hash_to_id:
            del self._hash_to_id[meta.content_hash]

        file_path = self.upload_dir / meta.filename
        if file_path.exists():
            file_path.unlink()

        self.vector_store.delete_document(document_id)
        del self.documents[document_id]
        self._save_metadata()
        logger.info(f"Deleted document {document_id}")
        return True

