from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field
from app.models.response import ApiResponse
from app.models.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationDetailResponse
)
from app.services.conversation_service import ConversationService
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
    service: ConversationService = Depends(get_conversation_service)
):
    try:
        conv = service.create_conversation(
            document_id=req.document_id,
            document_ids=req.document_ids,
            title=req.title
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
    limit: int = 50,
    offset: int = 0,
    include_empty: bool = Query(default=True, description="Whether to include empty conversations without user messages"),
    service: ConversationService = Depends(get_conversation_service)
):
    try:
        convs = service.list_conversations(limit=limit, offset=offset, include_empty=include_empty)
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
    service: ConversationService = Depends(get_conversation_service)
):
    conv = service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' was not found."
        )
    return ApiResponse(
        success=True,
        message="Conversation retrieved successfully.",
        data=conv.model_dump(mode="json")
    )


@router.patch("/{conversation_id}", response_model=ApiResponse)
async def update_conversation(
    conversation_id: str,
    req: ConversationUpdate,
    service: ConversationService = Depends(get_conversation_service)
):
    conv = service.update_conversation(
        conversation_id=conversation_id,
        title=req.title,
        status=req.status,
        document_ids=req.document_ids
    )
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID '{conversation_id}' was not found."
        )
    return ApiResponse(
        success=True,
        message="Conversation updated successfully.",
        data=conv.model_dump(mode="json")
    )


@router.delete("/{conversation_id}", response_model=ApiResponse)
async def delete_conversation(
    conversation_id: str,
    document_id: str = Query(..., min_length=1),
    service: ConversationService = Depends(get_conversation_service)
):
    success = service.delete_conversation(conversation_id, document_id)
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
    document_id: Optional[str] = Query(default=None, description="Optional document ID filter"),
    service: ConversationService = Depends(get_conversation_service)
):
    deleted_count = service.delete_all_conversations(document_id=document_id)
    return ApiResponse(
        success=True,
        message=f"Deleted {deleted_count} conversation(s) successfully.",
        data={"deleted_count": deleted_count}
    )

