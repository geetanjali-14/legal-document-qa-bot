from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from app.models.response import ApiResponse
from app.models.document import DocumentMetadata
from app.services.document_service import DocumentService
from app.services.pdf_service import ScannedPDFError, PDFExtractionError
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
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF documents are accepted."
        )

    try:
        content = await file.read()
        metadata = doc_service.process_document(content, file.filename)
        return ApiResponse(
            success=True,
            message="Document uploaded and indexed successfully.",
            data=metadata.model_dump(mode="json")
        )
    except ScannedPDFError as se:
        logger.warning(f"Scanned PDF uploaded: {file.filename} - {str(se)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(se)
        )
    except PDFExtractionError as pe:
        logger.warning(f"PDF extraction error for {file.filename}: {str(pe)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(pe)
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


@router.delete("/{document_id}", response_model=ApiResponse)
async def delete_document(document_id: str, doc_service: DocumentService = Depends(get_document_service)):
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
