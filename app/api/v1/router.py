import mimetypes
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import logger
from app.core.errors import (
    ResourceLimitError,
    FileSizeLimitExceededError,
    ChunkLimitExceededError
)
from app.services.document_service import DocumentService
from app.services.conversation_service import ConversationService
from app.services.pdf_service import ScannedPDFError, PDFExtractionError
from app.services.image_service import ImageExtractionError, OCRNoTextError
from app.models.chat import ChatRequest
from app.api.routes_chat import ask_question as internal_ask_question, get_services as get_chat_services
from app.api.v1.schemas import (
    V1ErrorResponse,
    V1HealthResponse,
    V1DocumentUploadResponse,
    V1DocumentDetailResponse,
    V1DocumentListResponse,
    V1DocumentDeleteResponse,
    V1ChatRequest,
    V1ChatResponse,
    V1SourceItem,
    V1ConversationCreateRequest,
    V1ConversationResponse,
    V1ConversationListResponse,
    V1ConversationDetailResponse,
    V1MessageItem
)

router = APIRouter(prefix="/v1", tags=["v1 Public API"])


def json_error(status_code: int, code: str, message: str, details: Optional[dict] = None) -> JSONResponse:
    """Helper to return standard formatted v1 error payload."""
    payload = {
        "error": {
            "code": code,
            "message": message
        }
    }
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def get_doc_service() -> DocumentService:
    from app.main import app_state
    if "document_service" not in app_state:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="DocumentService not available")
    return app_state["document_service"]


def get_conv_service() -> ConversationService:
    from app.main import app_state
    if "conversation_service" not in app_state:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ConversationService not available")
    return app_state["conversation_service"]


# ==========================================
# 1. Health
# ==========================================
@router.get("/health", response_model=V1HealthResponse)
async def v1_health():
    """
    Standard health check endpoint.
    Reports operational status without exposing underlying internal credentials or paths.
    """
    return V1HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        rag_provider=settings.RAG_PROVIDER,
        llm_provider=settings.LLM_PROVIDER
    )


# ==========================================
# 2. Document Management
# ==========================================
@router.get("/documents", response_model=V1DocumentListResponse)
async def v1_list_documents(doc_service: DocumentService = Depends(get_doc_service)):
    """List all registered legal documents."""
    docs = doc_service.list_documents()
    items = [
        V1DocumentDetailResponse(
            document_id=d.document_id,
            filename=d.filename,
            original_filename=d.original_filename,
            file_size_bytes=d.file_size_bytes,
            page_count=d.page_count,
            chunk_count=d.chunk_count,
            content_hash=d.content_hash,
            status=d.status,
            created_at=d.created_at.isoformat()
        )
        for d in docs
    ]
    return V1DocumentListResponse(documents=items, total=len(items))


@router.post("/documents", response_model=V1DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def v1_upload_document(
    file: UploadFile = File(...),
    doc_service: DocumentService = Depends(get_doc_service)
):
    """
    Upload and index a legal document synchronously.
    Accepts PDF and supported document/image formats.
    """
    if settings.DEMO_MODE:
        return json_error(
            status.HTTP_403_FORBIDDEN,
            "DEMO_MODE_RESTRICTION",
            "Document uploads are disabled in public demo mode."
        )

    if not file.filename:
        return json_error(status.HTTP_400_BAD_REQUEST, "INVALID_FILENAME", "Filename is required.")

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.SUPPORTED_DOCUMENT_EXTENSIONS:
        return json_error(
            status.HTTP_400_BAD_REQUEST,
            "UNSUPPORTED_MEDIA_TYPE",
            f"Unsupported file format '{file_ext}'. Supported formats: {', '.join(settings.SUPPORTED_DOCUMENT_EXTENSIONS)}"
        )

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        return json_error(
            status.HTTP_400_BAD_REQUEST,
            "FILE_TOO_LARGE",
            f"File size exceeds maximum allowed limit of {settings.MAX_FILE_SIZE_MB}MB."
        )

    try:
        content = await file.read()
        metadata = doc_service.process_document(content, file.filename)
        return V1DocumentUploadResponse(
            document_id=metadata.document_id,
            filename=metadata.original_filename,
            status=metadata.status,
            page_count=metadata.page_count,
            chunk_count=metadata.chunk_count,
            content_hash=metadata.content_hash,
            created_at=metadata.created_at.isoformat()
        )
    except ResourceLimitError as rle:
        return json_error(
            status.HTTP_400_BAD_REQUEST,
            getattr(rle, "error_category", "RESOURCE_LIMIT_EXCEEDED").upper(),
            str(rle)
        )
    except ScannedPDFError:
        return json_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "SCANNED_PDF_REJECTED",
            "Scanned or image-only PDF cannot be processed without OCR."
        )
    except PDFExtractionError as pe:
        return json_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "PDF_EXTRACTION_FAILED",
            f"Failed to extract text from PDF: {str(pe)}"
        )
    except Exception as e:
        logger.error(f"[v1] Unexpected error uploading document: {e}")
        return json_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PROCESSING_ERROR",
            "An error occurred while processing the document."
        )


@router.get("/documents/{document_id}", response_model=V1DocumentDetailResponse)
async def v1_get_document(
    document_id: str,
    doc_service: DocumentService = Depends(get_doc_service)
):
    """Retrieve metadata and indexing status for a document."""
    doc = doc_service.get_document(document_id)
    if not doc:
        return json_error(status.HTTP_404_NOT_FOUND, "DOCUMENT_NOT_FOUND", f"Document with ID '{document_id}' not found.")

    return V1DocumentDetailResponse(
        document_id=doc.document_id,
        filename=doc.filename,
        original_filename=doc.original_filename,
        file_size_bytes=doc.file_size_bytes,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        content_hash=doc.content_hash,
        status=doc.status,
        created_at=doc.created_at.isoformat()
    )


@router.delete("/documents/{document_id}", response_model=V1DocumentDeleteResponse)
async def v1_delete_document(
    document_id: str,
    doc_service: DocumentService = Depends(get_doc_service)
):
    """Delete a document and purge all associated indexed vectors."""
    if settings.DEMO_MODE:
        return json_error(
            status.HTTP_403_FORBIDDEN,
            "DEMO_MODE_RESTRICTION",
            "Document deletion is disabled in public demo mode."
        )

    deleted = doc_service.delete_document(document_id)
    if not deleted:
        return json_error(status.HTTP_404_NOT_FOUND, "DOCUMENT_NOT_FOUND", f"Document with ID '{document_id}' not found.")

    return V1DocumentDeleteResponse(
        success=True,
        document_id=document_id,
        message="Document and indexed vectors deleted successfully."
    )


# ==========================================
# 3. Chat Endpoint
# ==========================================
@router.post("/chat", response_model=V1ChatResponse)
async def v1_chat(
    req: V1ChatRequest,
    raw_request: Request,
    response: Response,
    services: dict = Depends(get_chat_services)
):
    """
    Query legal documents and receive grounded answers with citations.
    Reuses existing AgentOrchestrator and application pipelines.
    """
    if not req.question or not req.question.strip():
        return json_error(status.HTTP_400_BAD_REQUEST, "INVALID_QUERY", "Question cannot be empty.")

    if len(req.question) > settings.MAX_QUERY_CHARS:
        return json_error(
            status.HTTP_400_BAD_REQUEST,
            "QUERY_TOO_LARGE",
            f"Question length exceeds maximum allowed limit of {settings.MAX_QUERY_CHARS} characters."
        )

    # Verify document if provided
    if req.document_id and req.document_id.strip() and req.document_id.lower() not in ("none", "null"):
        doc = services["document"].get_document(req.document_id)
        if not doc:
            return json_error(status.HTTP_404_NOT_FOUND, "DOCUMENT_NOT_FOUND", f"Document with ID '{req.document_id}' not found.")

    # Delegate to internal ask_question handler
    chat_req = ChatRequest(
        question=req.question,
        document_id=req.document_id,
        conversation_id=req.conversation_id,
        top_k=req.top_k
    )

    try:
        api_resp = await internal_ask_question(
            request=chat_req,
            raw_request=raw_request,
            response=response,
            services=services
        )
    except HTTPException as he:
        code = "CHAT_ERROR"
        if he.status_code == status.HTTP_404_NOT_FOUND:
            code = "NOT_FOUND"
        elif he.status_code == status.HTTP_400_BAD_REQUEST:
            code = "INVALID_REQUEST"
        return json_error(he.status_code, code, str(he.detail))
    except Exception as e:
        logger.error(f"[v1] Chat generation error: {e}")
        return json_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "GENERATION_ERROR", str(e))

    chat_data = api_resp.data
    sources_raw = chat_data.get("sources", [])
    sources: List[V1SourceItem] = []
    for s in sources_raw:
        sources.append(V1SourceItem(
            document_id=s.get("document_id") or (req.document_id or ""),
            chunk_id=s.get("chunk_id"),
            page_number=s.get("page_number", 1),
            section=s.get("section", "General"),
            section_title=s.get("section_title"),
            clause_number=s.get("clause_number"),
            text_snippet=s.get("text_snippet") or s.get("text"),
            relevance_score=s.get("relevance_score") or s.get("similarity_score")
        ))

    return V1ChatResponse(
        answer=chat_data.get("answer", ""),
        conversation_id=chat_data.get("conversation_id", ""),
        document_id=chat_data.get("document_id"),
        sources=sources,
        intent=chat_data.get("intent"),
        confidence=chat_data.get("confidence"),
        model=chat_data.get("model"),
        disclaimer=chat_data.get("disclaimer")
    )


# ==========================================
# 4. Conversations
# ==========================================
@router.post("/conversations", response_model=V1ConversationResponse, status_code=status.HTTP_201_CREATED)
async def v1_create_conversation(
    req: V1ConversationCreateRequest,
    raw_request: Request,
    response: Response,
    conv_service: ConversationService = Depends(get_conv_service)
):
    """Create a persistent conversation session."""
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    try:
        conv = conv_service.create_conversation(
            document_id=req.document_id,
            document_ids=req.document_ids,
            title=req.title,
            session_id=session_id
        )
        return V1ConversationResponse(
            id=conv.conversation_id,
            title=conv.title,
            status=conv.status,
            document_ids=conv.document_ids,
            message_count=0,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat()
        )
    except Exception as e:
        logger.error(f"[v1] Error creating conversation: {e}")
        return json_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "CONVERSATION_CREATE_FAILED", "Could not create conversation.")


@router.get("/conversations", response_model=V1ConversationListResponse)
async def v1_list_conversations(
    raw_request: Request,
    response: Response,
    limit: int = 50,
    offset: int = 0,
    conv_service: ConversationService = Depends(get_conv_service)
):
    """List conversation sessions."""
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    filter_session_id = session_id if settings.DEMO_MODE else None
    convs = conv_service.list_conversations(limit=limit, offset=offset, session_id=filter_session_id)
    items = [
        V1ConversationResponse(
            id=c.conversation_id,
            title=c.title,
            status=c.status,
            document_ids=c.document_ids,
            message_count=c.message_count if hasattr(c, "message_count") else 0,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat()
        )
        for c in convs
    ]
    return V1ConversationListResponse(conversations=items, total=len(items))


@router.get("/conversations/{conversation_id}", response_model=V1ConversationDetailResponse)
async def v1_get_conversation(
    conversation_id: str,
    raw_request: Request,
    response: Response,
    conv_service: ConversationService = Depends(get_conv_service)
):
    """Retrieve full conversation details including messages and source citations."""
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    raw_conv = conv_service.repository.get_conversation(conversation_id)
    if not raw_conv:
        return json_error(status.HTTP_404_NOT_FOUND, "CONVERSATION_NOT_FOUND", f"Conversation '{conversation_id}' not found.")
    if settings.DEMO_MODE and raw_conv.session_id and raw_conv.session_id != session_id:
        return json_error(status.HTTP_404_NOT_FOUND, "CONVERSATION_NOT_FOUND", f"Conversation '{conversation_id}' not found.")

    conv = conv_service.get_conversation(conversation_id)
    if not conv:
        return json_error(status.HTTP_404_NOT_FOUND, "CONVERSATION_NOT_FOUND", f"Conversation '{conversation_id}' not found.")

    msg_items = []
    for m in conv.messages:
        sources_list = []
        if getattr(m, "sources", None):
            for s in m.sources:
                sources_list.append(V1SourceItem(
                    document_id=getattr(s, "document_id", "") or "",
                    chunk_id=getattr(s, "chunk_id", None),
                    page_number=getattr(s, "page_number", 1) or 1,
                    section=getattr(s, "section", "General") or "General",
                    section_title=getattr(s, "section_title", None),
                    clause_number=getattr(s, "clause_number", None),
                    text_snippet=getattr(s, "text_snippet", None)
                ))
        msg_items.append(V1MessageItem(
            id=m.message_id,
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat(),
            sources=sources_list
        ))

    return V1ConversationDetailResponse(
        id=conv.conversation_id,
        title=conv.title,
        status=conv.status,
        document_ids=conv.document_ids,
        messages=msg_items,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat()
    )


@router.delete("/conversations/{conversation_id}")
async def v1_delete_conversation(
    conversation_id: str,
    raw_request: Request,
    response: Response,
    conv_service: ConversationService = Depends(get_conv_service)
):
    """Delete a conversation session."""
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    filter_session_id = session_id if settings.DEMO_MODE else None
    deleted = conv_service.delete_conversation(conversation_id, session_id=filter_session_id)
    if not deleted:
        return json_error(status.HTTP_404_NOT_FOUND, "CONVERSATION_NOT_FOUND", f"Conversation '{conversation_id}' not found.")
    return {"success": True, "conversation_id": conversation_id, "message": "Conversation deleted successfully."}
