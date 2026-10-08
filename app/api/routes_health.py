from fastapi import APIRouter
from app.models.response import ApiResponse
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=ApiResponse)
async def health_check():
    return ApiResponse(
        success=True,
        message="System operational",
        data={
            "status": "healthy",
            "app_name": settings.APP_NAME,
            "llm_provider": settings.LLM_PROVIDER,
            "embedding_provider": settings.EMBEDDING_PROVIDER,
            "supported_document_formats": list(settings.SUPPORTED_DOCUMENT_EXTENSIONS),
            "supported_image_formats": list(settings.SUPPORTED_IMAGE_EXTENSIONS)
        }
    )
