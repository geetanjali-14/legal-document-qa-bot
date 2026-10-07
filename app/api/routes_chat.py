import time
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends, Request, Response
from app.models.response import ApiResponse
from app.models.chat import ChatRequest, ChatResponse
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService, LLMResponse
from app.services.citation_service import CitationService
from app.services.document_service import DocumentService
from app.core.config import settings
from app.core.logging import logger
from app.core.telemetry import (
    ChatTelemetry,
    record_chat_telemetry,
    pricing_registry
)

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
async def ask_question(
    request: ChatRequest,
    raw_request: Request,
    response: Response,
    services: dict = Depends(get_services)
):
    # 1. Establish unique request identifier
    client_request_id = raw_request.headers.get("x-request-id") or raw_request.headers.get("X-Request-ID")
    request_id = client_request_id.strip() if client_request_id else f"req_{uuid.uuid4().hex[:16]}"
    response.headers["X-Request-ID"] = request_id

    t_request_start = time.perf_counter()

    doc_service: DocumentService = services["document"]
    retrieval_service: RetrievalService = services["retrieval"]
    llm_service: LLMService = services["llm"]
    citation_service: CitationService = services["citation"]

    # 2. Verify document exists
    doc = doc_service.get_document(request.document_id)
    if not doc:
        logger.warning(f"[{request_id}] Document with ID {request.document_id} not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {request.document_id} was not found."
        )

    # 3. Retrieve relevant chunks
    try:
        retrieved_results = retrieval_service.retrieve(
            document_id=request.document_id,
            query=request.question,
            top_k=request.top_k
        )
        retrieval_latency_ms = getattr(retrieval_service, "last_retrieval_latency_ms", 0.0)
        embedding_latency_ms = getattr(retrieval_service, "last_embedding_latency_ms", 0.0)
    except Exception as e:
        logger.error(f"[{request_id}] Retrieval error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving relevant document passages."
        )

    # If no chunks passed similarity threshold
    if not retrieved_results:
        total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            document_id=request.document_id,
            status="insufficient_context",
            total_latency_ms=round(total_latency_ms, 2),
            retrieval_latency_ms=round(retrieval_latency_ms, 2),
            embedding_latency_ms=round(embedding_latency_ms, 2),
            llm_latency_ms=None,
            retrieved_chunks_count=0,
            token_usage_type="unknown",
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            llm_provider=settings.LLM_PROVIDER,
            llm_model=settings.LLM_MODEL,
            embedding_provider=settings.EMBEDDING_PROVIDER,
            embedding_model=settings.EMBEDDING_MODEL,
            estimated_llm_cost=None,
            estimated_embedding_cost=None,
            estimated_total_cost=None
        )
        record_chat_telemetry(telemetry)

        return ApiResponse(
            success=True,
            message="Question answered",
            data=ChatResponse(
                answer="I couldn't find enough information in the uploaded document to answer this question.",
                sources=[],
                confidence="insufficient_context",
                request_id=request_id,
                telemetry=telemetry
            ).model_dump()
        )

    # 4. Create verifiable citations
    citations = citation_service.create_citations(retrieved_results)

    # 5. Format context for LLM
    context_chunks = [
        f"[Section: {chunk.section} | Page: {chunk.page_number}]\n{chunk.text}"
        for chunk, _ in retrieved_results
    ]

    # 6. Generate grounded response
    t_llm_call_start = time.perf_counter()
    try:
        llm_result = llm_service.generate_answer(
            question=request.question,
            context_chunks=context_chunks,
            history=request.history
        )
    except Exception as e:
        logger.error(f"[{request_id}] LLM generation failure: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate answer from language model provider."
        )

    measured_llm_latency_ms = max(0.0, (time.perf_counter() - t_llm_call_start) * 1000.0)

    if isinstance(llm_result, LLMResponse):
        answer_text = llm_result.content
        llm_latency_ms = llm_result.latency_ms if llm_result.latency_ms > 0 else measured_llm_latency_ms
        input_tokens = llm_result.input_tokens
        output_tokens = llm_result.output_tokens
        total_tokens = llm_result.total_tokens
        token_usage_type = llm_result.token_usage_type
        est_input_tokens = llm_result.estimated_input_tokens
        est_output_tokens = llm_result.estimated_output_tokens
        est_total_tokens = llm_result.estimated_total_tokens
        est_method = llm_result.estimation_method
        llm_provider = llm_result.provider or settings.LLM_PROVIDER
        llm_model = llm_result.model or settings.LLM_MODEL
    else:
        answer_text = str(llm_result)
        llm_latency_ms = measured_llm_latency_ms
        input_tokens = None
        output_tokens = None
        total_tokens = None
        token_usage_type = "unknown"
        est_input_tokens = None
        est_output_tokens = None
        est_total_tokens = None
        est_method = None
        llm_provider = settings.LLM_PROVIDER
        llm_model = settings.LLM_MODEL

    confidence = "supported"
    if "couldn't find enough information" in answer_text.lower():
        confidence = "insufficient_context"
        citations = []

    # 7. Calculate estimated costs
    if token_usage_type == "actual":
        estimated_llm_cost = pricing_registry.calculate_cost(
            provider=llm_provider,
            model=llm_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
    elif token_usage_type == "estimated":
        estimated_llm_cost = pricing_registry.calculate_cost(
            provider=llm_provider,
            model=llm_model,
            input_tokens=est_input_tokens,
            output_tokens=est_output_tokens
        )
    else:
        estimated_llm_cost = None

    # Embedding cost
    emb_tokens = getattr(retrieval_service.embedding_service, "last_tokens", None)
    estimated_embedding_cost = pricing_registry.calculate_cost(
        provider=settings.EMBEDDING_PROVIDER,
        model=settings.EMBEDDING_MODEL,
        input_tokens=emb_tokens,
        output_tokens=0
    )

    if estimated_llm_cost is not None or estimated_embedding_cost is not None:
        estimated_total_cost = round((estimated_llm_cost or 0.0) + (estimated_embedding_cost or 0.0), 8)
    else:
        estimated_total_cost = None

    total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)

    # 8. Assemble structured telemetry (conservatively omitting document text / prompts)
    telemetry = ChatTelemetry(
        request_id=request_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        document_id=request.document_id,
        status=confidence,
        total_latency_ms=round(total_latency_ms, 2),
        retrieval_latency_ms=round(retrieval_latency_ms, 2),
        embedding_latency_ms=round(embedding_latency_ms, 2),
        llm_latency_ms=round(llm_latency_ms, 2),
        retrieved_chunks_count=len(retrieved_results),
        token_usage_type=token_usage_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_input_tokens=est_input_tokens,
        estimated_output_tokens=est_output_tokens,
        estimated_total_tokens=est_total_tokens,
        estimation_method=est_method,
        llm_provider=llm_provider,
        llm_model=llm_model,
        embedding_provider=settings.EMBEDDING_PROVIDER,
        embedding_model=settings.EMBEDDING_MODEL,
        estimated_llm_cost=estimated_llm_cost,
        estimated_embedding_cost=estimated_embedding_cost,
        estimated_total_cost=estimated_total_cost
    )
    record_chat_telemetry(telemetry)

    return ApiResponse(
        success=True,
        message="Question answered",
        data=ChatResponse(
            answer=answer_text,
            sources=citations,
            confidence=confidence,
            request_id=request_id,
            telemetry=telemetry
        ).model_dump()
    )

