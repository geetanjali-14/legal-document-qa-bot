from typing import List
from pathlib import Path
import mimetypes
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from fastapi.responses import FileResponse
from app.models.response import ApiResponse
from app.models.document import DocumentMetadata
from app.services.document_service import DocumentService
from app.services.pdf_service import ScannedPDFError, PDFExtractionError
from app.services.image_service import ImageExtractionError, OCRNoTextError
from app.core.config import settings
from app.core.errors import ResourceLimitError
from app.core.logging import logger

router = APIRouter(prefix="/documents", tags=["Documents"])


def get_document_service() -> DocumentService:
    from app.main import app_state
    return app_state["document_service"]


@router.post("/upload", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    doc_service: DocumentService = Depends(get_document_service)
):
    if settings.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document uploads are disabled in public demo mode. Please explore the pre-loaded legal sample documents."
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required."
        )

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.SUPPORTED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file format: Only PDF documents are accepted, along with supported images ({', '.join(settings.SUPPORTED_DOCUMENT_EXTENSIONS)}). Unsupported format '{file_ext}'."
        )

    # Early rejection if content length header indicates oversized file
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size ({file.size} bytes) exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_MB}MB. [file_too_large]",
            headers={"X-Error-Category": "file_too_large"}
        )

    try:
        content = await file.read()
        metadata = doc_service.process_document(content, file.filename)
        return ApiResponse(
            success=True,
            message="Document uploaded and indexed successfully.",
            data=metadata.model_dump(mode="json")
        )
    except ResourceLimitError as rle:
        logger.warning(f"Resource limit exceeded for {file.filename}: [{rle.error_category}] {rle.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{rle.message} [{rle.error_category}]",
            headers={"X-Error-Category": rle.error_category}
        )
    except ScannedPDFError as se:
        logger.warning(f"Scanned PDF uploaded: {file.filename} - {str(se)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(se)
        )
    except OCRNoTextError as one:
        logger.warning(f"Image document OCR extracted no text for {file.filename}: {str(one)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(one)
        )
    except PDFExtractionError as pe:
        logger.warning(f"PDF extraction error for {file.filename}: {str(pe)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(pe)
        )
    except ImageExtractionError as ie:
        logger.warning(f"Image processing error for {file.filename}: {str(ie)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ie)
        )
    except ValueError as ve:
        logger.warning(f"Validation error for {file.filename}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Unexpected error processing document {file.filename}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error processing the legal document."
        )


@router.get("", response_model=ApiResponse)
async def list_documents(doc_service: DocumentService = Depends(get_document_service)):
    docs = doc_service.list_documents()
    return ApiResponse(
        success=True,
        message="Documents retrieved successfully.",
        data=[d.model_dump(mode="json") for d in docs]
    )


@router.get("/{document_id}", response_model=ApiResponse)
async def get_document(document_id: str, doc_service: DocumentService = Depends(get_document_service)):
    doc = doc_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} was not found."
        )
    return ApiResponse(
        success=True,
        message="Document details retrieved.",
        data=doc.model_dump(mode="json")
    )


@router.get("/{document_id}/file")
async def get_document_file(document_id: str, doc_service: DocumentService = Depends(get_document_service)):
    doc = doc_service.get_document(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} was not found."
        )

    file_path = (doc_service.upload_dir / doc.filename).resolve()
    upload_root = doc_service.upload_dir.resolve()
    if not str(file_path).startswith(str(upload_root)) or not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored file for document {document_id} was not found."
        )

    # Determine media type based on file extension
    media_type, _ = mimetypes.guess_type(str(file_path))
    if not media_type:
        media_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"

    # Sanitize header filename to prevent header injection or unsafe characters
    safe_download_name = doc_service.sanitize_filename(doc.original_filename or f"document{file_path.suffix}")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=safe_download_name,
        headers={"Content-Disposition": f"inline; filename=\"{safe_download_name}\""}
    )


@router.get("/{document_id}/structure", response_model=ApiResponse)
async def get_document_structure(document_id: str, doc_service: DocumentService = Depends(get_document_service)):
    """Retrieve hierarchical legal AST, sections, definitions, and cross-references."""
    structure = doc_service.get_document_structure(document_id)
    if not structure:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Structural analysis for document {document_id} was not found."
        )
    return ApiResponse(
        success=True,
        message="Document structure retrieved.",
        data=structure.model_dump(mode="json")
    )


@router.delete("/{document_id}", response_model=ApiResponse)
async def delete_document(document_id: str, doc_service: DocumentService = Depends(get_document_service)):
    if settings.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document deletion is disabled in public demo mode."
        )

    deleted = doc_service.delete_document(document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} was not found."
        )
    return ApiResponse(
        success=True,
        message="Document and indexed vectors deleted successfully."
    )
