from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from app.models.response import ApiResponse
from app.models.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationDetailResponse
)
from app.services.conversation_service import ConversationService
from app.core.config import settings
from app.core.logging import logger

router = APIRouter(prefix="/conversations", tags=["Conversations"])


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    status: Optional[str] = None
    document_ids: Optional[List[str]] = None


def get_conversation_service() -> ConversationService:
    from app.main import app_state
    if "conversation_service" not in app_state:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation service is not initialized."
        )
    return app_state["conversation_service"]


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    req: ConversationCreate,
    raw_request: Request,
    response: Response,
    service: ConversationService = Depends(get_conversation_service)
):
    from app.core.security import get_or_create_session_id, rate_limiter
    session_id, _ = get_or_create_session_id(raw_request, response)

    client_ip = raw_request.client.host if raw_request.client else "unknown"
    rate_key = f"conv_create:{session_id}:{client_ip}"
    allowed, retry_after = rate_limiter.is_allowed(rate_key, max_requests=settings.RATE_LIMIT_CONV_PER_MINUTE, window_seconds=60)
    if not allowed:
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Please wait {retry_after} seconds before creating a conversation.",
            headers={"Retry-After": str(retry_after)}
        )

    try:
        conv = service.create_conversation(
            document_id=req.document_id,
            document_ids=req.document_ids,
            title=req.title,
            session_id=session_id
        )
        return ApiResponse(
            success=True,
            message="Conversation created successfully.",
            data=conv.model_dump(mode="json")
        )
    except Exception as e:
        logger.error(f"Error creating conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error creating conversation."
        )


@router.get("", response_model=ApiResponse)
async def list_conversations(
    raw_request: Request,
    response: Response,
    limit: int = 50,
    offset: int = 0,
    include_empty: bool = Query(default=True, description="Whether to include empty conversations without user messages"),
    service: ConversationService = Depends(get_conversation_service)
):
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    try:
        filter_session_id = session_id if settings.DEMO_MODE else None
        convs = service.list_conversations(
            limit=limit,
            offset=offset,
            include_empty=include_empty,
            session_id=filter_session_id
        )
        return ApiResponse(
            success=True,
            message="Conversations retrieved successfully.",
            data=[c.model_dump(mode="json") for c in convs]
        )
    except Exception as e:
        logger.error(f"Error listing conversations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error listing conversations."
        )


@router.get("/{conversation_id}", response_model=ApiResponse)
async def get_conversation(
    conversation_id: str,
    raw_request: Request,
    response: Response,
    service: ConversationService = Depends(get_conversation_service)
):
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    raw_conv = service.repository.get_conversation(conversation_id)
    if not raw_conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' was not found."
        )
    if settings.DEMO_MODE and (raw_conv.session_id != session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' was not found."
        )

    conv = service.get_conversation(conversation_id)
    return ApiResponse(
        success=True,
        message="Conversation retrieved successfully.",
        data=conv.model_dump(mode="json")
    )


@router.patch("/{conversation_id}", response_model=ApiResponse)
async def update_conversation(
    conversation_id: str,
    req: ConversationUpdate,
    raw_request: Request,
    response: Response,
    service: ConversationService = Depends(get_conversation_service)
):
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    raw_conv = service.repository.get_conversation(conversation_id)
    if not raw_conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' was not found."
        )
    if settings.DEMO_MODE and (raw_conv.session_id != session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' was not found."
        )

    conv = service.update_conversation(
        conversation_id=conversation_id,
        title=req.title,
        status=req.status,
        document_ids=req.document_ids
    )
    return ApiResponse(
        success=True,
        message="Conversation updated successfully.",
        data=conv.model_dump(mode="json")
    )


@router.delete("/{conversation_id}", response_model=ApiResponse)
async def delete_conversation(
    conversation_id: str,
    raw_request: Request,
    response: Response,
    document_id: str = Query(..., min_length=1),
    service: ConversationService = Depends(get_conversation_service)
):
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    filter_session_id = session_id if settings.DEMO_MODE else None
    success = service.delete_conversation(conversation_id, document_id, session_id=filter_session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' was not found."
        )
    return ApiResponse(
        success=True,
        message="Conversation deleted successfully.",
        data={"conversation_id": conversation_id, "deleted": True}
    )


@router.delete("", response_model=ApiResponse)
async def delete_all_conversations(
    raw_request: Request,
    response: Response,
    document_id: Optional[str] = Query(default=None, description="Optional document ID filter"),
    service: ConversationService = Depends(get_conversation_service)
):
    from app.core.security import get_or_create_session_id
    session_id, _ = get_or_create_session_id(raw_request, response)

    filter_session_id = session_id if settings.DEMO_MODE else None
    deleted_count = service.delete_all_conversations(document_id=document_id, session_id=filter_session_id)
    return ApiResponse(
        success=True,
        message=f"Deleted {deleted_count} conversation(s) successfully.",
        data={"deleted_count": deleted_count}
    )

