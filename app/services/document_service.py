import json
import uuid
import re
from pathlib import Path
from typing import List, Optional, Dict
from app.models.document import DocumentMetadata, DocumentChunk
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.core.config import settings
from app.core.logging import logger


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
        self._load_metadata()

    def _load_metadata(self) -> None:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        meta = DocumentMetadata(**item)
                        self.documents[meta.document_id] = meta
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

    def process_document(self, file_bytes: bytes, original_filename: str) -> DocumentMetadata:
        """
        Validate, store, extract, chunk, embed, and index an uploaded document.
        """
        # Validate file size
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise ValueError(f"File size exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_MB}MB.")

        if not file_bytes.startswith(b"%PDF"):
            raise ValueError("Invalid file format. Only standard PDF documents are supported.")

        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        safe_name = f"{doc_id}_{self.sanitize_filename(original_filename)}"
        saved_path = self.upload_dir / safe_name

        with open(saved_path, "wb") as f:
            f.write(file_bytes)

        try:
            # 1. Extract text and pages
            pages = self.pdf_service.extract_text_and_pages(saved_path)

            # 2. Chunk text with section awareness
            chunks = self.chunking_service.chunk_document(
                document_id=doc_id,
                document_name=original_filename,
                pages=pages
            )

            if not chunks:
                raise ValueError("No extractable chunks found in document.")

            if len(chunks) > settings.MAX_CHUNKS_PER_DOC:
                raise ValueError(
                    f"Document generated {len(chunks)} chunks, exceeding max limit of {settings.MAX_CHUNKS_PER_DOC}."
                )

            # 3. Generate embeddings
            chunk_texts = [c.text for c in chunks]
            embeddings = self.embedding_service.embed_texts(chunk_texts)

            # 4. Store in vector database
            self.vector_store.add_document(doc_id, chunks, embeddings)

            meta = DocumentMetadata(
                document_id=doc_id,
                filename=safe_name,
                original_filename=original_filename,
                file_size_bytes=len(file_bytes),
                page_count=len(pages),
                chunk_count=len(chunks),
                status="processed"
            )
            self.documents[doc_id] = meta
            self._save_metadata()

            logger.info(f"Successfully processed document {original_filename} (ID: {doc_id})")
            return meta

        except Exception as e:
            # Clean up on failure
            if saved_path.exists():
                saved_path.unlink()
            self.vector_store.delete_document(doc_id)
            raise e

    def list_documents(self) -> List[DocumentMetadata]:
        return list(self.documents.values())

    def get_document(self, document_id: str) -> Optional[DocumentMetadata]:
        return self.documents.get(document_id)

    def delete_document(self, document_id: str) -> bool:
        if document_id not in self.documents:
            return False

        meta = self.documents[document_id]
        file_path = self.upload_dir / meta.filename
        if file_path.exists():
            file_path.unlink()

        self.vector_store.delete_document(document_id)
        del self.documents[document_id]
        self._save_metadata()
        logger.info(f"Deleted document {document_id}")
        return True
