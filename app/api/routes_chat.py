from fastapi import APIRouter, HTTPException, status, Depends
from app.models.response import ApiResponse
from app.models.chat import ChatRequest, ChatResponse
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService
from app.services.citation_service import CitationService
from app.services.document_service import DocumentService
from app.core.logging import logger

router = APIRouter(prefix="/chat", tags=["Chat"])


def get_services():
    from app.main import app_state
    return {
        "retrieval": app_state["retrieval_service"],
        "llm": app_state["llm_service"],
        "citation": app_state["citation_service"],
        "document": app_state["document_service"]
    }


@router.post("", response_model=ApiResponse)
async def ask_question(request: ChatRequest, services: dict = Depends(get_services)):
    doc_service: DocumentService = services["document"]
    retrieval_service: RetrievalService = services["retrieval"]
    llm_service: LLMService = services["llm"]
    citation_service: CitationService = services["citation"]

    # 1. Verify document exists
    doc = doc_service.get_document(request.document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {request.document_id} was not found."
        )

    # 2. Retrieve relevant chunks
    try:
        retrieved_results = retrieval_service.retrieve(
            document_id=request.document_id,
            query=request.question,
            top_k=request.top_k
        )
    except Exception as e:
        logger.error(f"Retrieval error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving relevant document passages."
        )

    # If no chunks passed similarity threshold
    if not retrieved_results:
        return ApiResponse(
            success=True,
            message="Question answered",
            data=ChatResponse(
                answer="I couldn't find enough information in the uploaded document to answer this question.",
                sources=[],
                confidence="insufficient_context"
            ).model_dump()
        )

    # 3. Create verifiable citations
    citations = citation_service.create_citations(retrieved_results)

    # 4. Format context for LLM
    context_chunks = [
        f"[Section: {chunk.section} | Page: {chunk.page_number}]\n{chunk.text}"
        for chunk, _ in retrieved_results
    ]

    # 5. Generate grounded response
    try:
        answer_text = llm_service.generate_answer(
            question=request.question,
            context_chunks=context_chunks,
            history=request.history
        )
    except Exception as e:
        logger.error(f"LLM generation failure: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate answer from language model provider."
        )

    confidence = "supported"
    if "couldn't find enough information" in answer_text.lower():
        confidence = "insufficient_context"
        citations = []

    return ApiResponse(
        success=True,
        message="Question answered",
        data=ChatResponse(
            answer=answer_text,
            sources=citations,
            confidence=confidence
        ).model_dump()
    )
