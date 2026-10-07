"""Deterministic Document Metadata Tool (P1-TOOL-01).

Retrieves authoritative metadata directly from indexed state with zero LLM tokens
and zero vector search operations.
"""
from typing import Optional
from app.models.agent import MetadataResult
from app.services.document_service import DocumentService
from app.core.logging import logger


class DocumentMetadataTool:
    def __init__(self, document_service: DocumentService):
        self.document_service = document_service

    def get_document_metadata(self, document_id: str) -> Optional[MetadataResult]:
        """
        Fetches authoritative document metadata deterministically.
        Consumes 0 LLM tokens and bypasses vector index.
        """
        doc = self.document_service.get_document(document_id)
        if not doc:
            logger.warning(f"[DocumentMetadataTool] Document not found: {document_id}")
            return None

        created_str = doc.created_at.isoformat() if hasattr(doc.created_at, "isoformat") else str(doc.created_at)

        return MetadataResult(
            document_id=doc.document_id,
            original_filename=doc.original_filename or doc.filename,
            filename=doc.filename,
            file_size_bytes=doc.file_size_bytes,
            page_count=doc.page_count,
            chunk_count=doc.chunk_count,
            content_hash=doc.content_hash,
            status=doc.status,
            created_at=created_str,
            embedding_provider=doc.embedding_provider,
            embedding_model=doc.embedding_model
        )

    def format_metadata_answer(self, meta: MetadataResult, specific_attribute: Optional[str] = None) -> str:
        """
        Generates deterministic, clear responses for metadata inquiries without calling the LLM.
        """
        if specific_attribute == "page_count":
            return f"The document '{meta.original_filename}' has {meta.page_count} page{'s' if meta.page_count != 1 else ''}."
        elif specific_attribute == "filename":
            return f"The filename of this document is '{meta.original_filename}'."
        elif specific_attribute == "file_size":
            kb = round(meta.file_size_bytes / 1024, 2)
            return f"The file size of '{meta.original_filename}' is {meta.file_size_bytes} bytes ({kb} KB)."
        elif specific_attribute == "chunk_count":
            return f"The document '{meta.original_filename}' is indexed into {meta.chunk_count} text chunks."
        elif specific_attribute == "created_at":
            return f"The document '{meta.original_filename}' was uploaded/indexed on {meta.created_at}."
        elif specific_attribute == "content_hash":
            return f"The SHA-256 content hash of '{meta.original_filename}' is {meta.content_hash}."
        else:
            kb = round(meta.file_size_bytes / 1024, 2)
            return (
                f"Document Metadata for '{meta.original_filename}':\n"
                f"- Document ID: {meta.document_id}\n"
                f"- Pages: {meta.page_count}\n"
                f"- File Size: {meta.file_size_bytes} bytes ({kb} KB)\n"
                f"- Indexed Chunks: {meta.chunk_count}\n"
                f"- Status: {meta.status}\n"
                f"- Content Hash: {meta.content_hash or 'N/A'}"
            )

