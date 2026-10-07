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
from app.core.errors import (
    ResourceLimitError,
    QueryLimitExceededError,
    ContextLimitExceededError,
    TokenBudgetExceededError,
    EmbeddingDimensionMismatchError
)
from app.core.telemetry import (
    ChatTelemetry,
    record_chat_telemetry,
    pricing_registry
)

router = APIRouter(prefix="/chat", tags=["Chat"])


def get_services():
    from app.main import app_state
    from app.services.intent_router import IntentRouter
    from app.services.tools.metadata_tool import DocumentMetadataTool
    from app.services.tools.profile_tool import DocumentProfileTool
    from app.services.tools.evidence_tool import EvidenceRetrievalTool
    from app.services.tools.structure_tool import SectionStructureTool
    from app.services.tools.reference_tools import CrossReferenceTool, DefinitionTool
    from app.services.tools.comparison_tool import MultiDocumentComparisonTool
    from app.services.legal_reasoning import (
        ConflictDetector,
        TemporalReasoner,
        ObligationExtractor,
        RiskAnalyzer
    )
    from app.services.agent_orchestrator import AgentOrchestrator

    doc_s = app_state["document_service"]
    ret_s = app_state["retrieval_service"]
    llm_s = app_state["llm_service"]
    cite_s = app_state["citation_service"]
    repo = app_state.get("conversation_repo")

    ev_tool = EvidenceRetrievalTool(retrieval_service=ret_s)

    # Build dynamically so test fixtures overriding doc_s, ret_s, llm_s have their active instances wired
    orch = AgentOrchestrator(
        intent_router=app_state.get("intent_router") or IntentRouter(),
        metadata_tool=DocumentMetadataTool(document_service=doc_s),
        profile_tool=DocumentProfileTool(document_service=doc_s, repository=repo),
        evidence_tool=ev_tool,
        llm_service=llm_s,
        citation_service=cite_s,
        structure_tool=SectionStructureTool(document_service=doc_s),
        cross_ref_tool=CrossReferenceTool(document_service=doc_s),
        definition_tool=DefinitionTool(document_service=doc_s),
        comparison_tool=MultiDocumentComparisonTool(document_service=doc_s, evidence_tool=ev_tool),
        conflict_detector=ConflictDetector(),
        temporal_reasoner=TemporalReasoner(),
        obligation_extractor=ObligationExtractor(),
        risk_analyzer=RiskAnalyzer()
    )

    return {
        "retrieval": ret_s,
        "llm": llm_s,
        "citation": cite_s,
        "document": doc_s,
        "conversation": app_state.get("conversation_service"),
        "orchestrator": orch
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

    # 2. Hard limit: validate query length before expensive retrieval or embedding
    if len(request.question) > settings.MAX_QUERY_CHARS:
        total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            document_id=request.document_id,
            status="rejected",
            error_category="query_too_large",
            total_latency_ms=round(total_latency_ms, 2),
            token_usage_type="unknown"
        )
        record_chat_telemetry(telemetry)
        logger.warning(f"[{request_id}] Query rejected: length ({len(request.question)}) > {settings.MAX_QUERY_CHARS}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User question length ({len(request.question)} characters) exceeds maximum allowed limit of {settings.MAX_QUERY_CHARS} characters. [query_too_large]",
            headers={"X-Error-Category": "query_too_large"}
        )

    # 3. Hard limit: validate top_k parameter ceiling
    if request.top_k is not None and request.top_k > settings.MAX_TOP_K:
        total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            document_id=request.document_id,
            status="rejected",
            error_category="context_limit_exceeded",
            total_latency_ms=round(total_latency_ms, 2),
            token_usage_type="unknown"
        )
        record_chat_telemetry(telemetry)
        logger.warning(f"[{request_id}] Request rejected: top_k ({request.top_k}) > {settings.MAX_TOP_K}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested top_k ({request.top_k}) exceeds maximum allowed limit of {settings.MAX_TOP_K}. [context_limit_exceeded]",
            headers={"X-Error-Category": "context_limit_exceeded"}
        )

    doc_service: DocumentService = services["document"]
    retrieval_service: RetrievalService = services["retrieval"]
    llm_service: LLMService = services["llm"]
    citation_service: CitationService = services["citation"]

    # 4. Verify document exists
    doc = doc_service.get_document(request.document_id)
    if not doc:
        logger.warning(f"[{request_id}] Document with ID {request.document_id} not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {request.document_id} was not found."
        )

    conv_service = services.get("conversation")
    active_conversation_id = None
    bounded_history = []
    if conv_service:
        try:
            conv_resp = conv_service.ensure_conversation_exists(
                conversation_id=request.conversation_id,
                document_id=request.document_id
            )
            active_conversation_id = conv_resp.conversation_id
            # Retrieve bounded history BEFORE appending current user message
            bounded_history = conv_service.get_bounded_history(
                conversation_id=active_conversation_id,
                max_turns=settings.MAX_HISTORY_TURNS,
                max_tokens=settings.MAX_HISTORY_TOKENS
            )
            # Persist user question
            conv_service.add_message(
                conversation_id=active_conversation_id,
                role="user",
                content=request.question
            )
        except ValueError as ve:
            logger.warning(f"[{request_id}] Conversation error: {str(ve)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(ve)
            )
        except Exception as e:
            logger.error(f"[{request_id}] Error ensuring conversation: {str(e)}")

    # Fallback to client-provided history if no persistent conversation history exists
    effective_history = bounded_history if bounded_history else (request.history or [])

    orchestrator = services.get("orchestrator")
    from app.services.query_service import decompose_query, clean_subquery_topic

    # 5. Compound query analysis & sub-question decomposition
    sub_questions = decompose_query(request.question)
    is_compound = len(sub_questions) > 1

    # Route through Controlled Agent Orchestrator if present and not handled by multi-part query splitting
    if orchestrator and not is_compound:
        try:
            agent_answer, agent_citations, agent_confidence, agent_trace, agent_telemetry = orchestrator.process_query(
                document_id=request.document_id,
                question=request.question,
                history=effective_history,
                top_k=request.top_k,
                request_id=request_id
            )

            if conv_service and active_conversation_id:
                try:
                    conv_service.add_message(
                        conversation_id=active_conversation_id,
                        role="assistant",
                        content=agent_answer,
                        intent=agent_trace.selected_intent,
                        evidence_state=agent_confidence,
                        sources=agent_citations,
                        telemetry=agent_telemetry
                    )
                except Exception as e:
                    logger.error(f"[{request_id}] Failed to persist assistant response message: {str(e)}")

            return ApiResponse(
                success=True,
                message="Question answered",
                data=ChatResponse(
                    answer=agent_answer,
                    sources=agent_citations,
                    confidence=agent_confidence,
                    request_id=request_id,
                    telemetry=agent_telemetry,
                    conversation_id=active_conversation_id,
                    audit_trace=agent_trace.model_dump()
                ).model_dump()
            )
        except EmbeddingDimensionMismatchError as dim_err:
            logger.error(f"[{request_id}] Embedding dimension mismatch: {str(dim_err)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(dim_err),
                headers={"X-Error-Category": "embedding_dimension_mismatch"}
            )
        except ContextLimitExceededError as cle:
            total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)
            telemetry = ChatTelemetry(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                document_id=request.document_id,
                status="rejected",
                error_category=cle.error_category,
                total_latency_ms=round(total_latency_ms, 2),
                token_usage_type="unknown"
            )
            record_chat_telemetry(telemetry)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{cle.message} [{cle.error_category}]",
                headers={"X-Error-Category": cle.error_category}
            )
        except TokenBudgetExceededError as tbe:
            total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)
            telemetry = ChatTelemetry(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                document_id=request.document_id,
                status="rejected",
                error_category=tbe.error_category,
                total_latency_ms=round(total_latency_ms, 2),
                token_usage_type="unknown"
            )
            record_chat_telemetry(telemetry)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{tbe.message} [{tbe.error_category}]",
                headers={"X-Error-Category": tbe.error_category}
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[{request_id}] Unexpected error in agent orchestrator: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal error occurred while processing your legal query."
            )

    # Extract corpus vocabulary for document-level grounding check if vector_store has chunks_by_doc
    chunks_map = getattr(retrieval_service.vector_store, "chunks_by_doc", None)
    doc_chunks_all = chunks_map.get(request.document_id, []) if isinstance(chunks_map, dict) else []
    doc_vocab = set()
    for dc in doc_chunks_all:
        doc_vocab.update(retrieval_service.extract_content_words(dc.text))
        if dc.section:
            doc_vocab.update(retrieval_service.extract_content_words(dc.section))

    def evaluate_subquestion_support(sub_q: str):
        qw = retrieval_service.extract_content_words(sub_q)
        # If specific content words in sub-question are completely absent from document
        if qw and (qw - doc_vocab):
            return False, []

        res = retrieval_service.retrieve(
            document_id=request.document_id,
            query=sub_q,
            top_k=request.top_k
        )
        if not res:
            return False, []
        if not qw:
            return True, res

        valid_chunks = []
        for chk, sc in res:
            cw = retrieval_service.extract_content_words(chk.text)
            if chk.section:
                cw.update(retrieval_service.extract_content_words(chk.section))
            mat = qw & cw
            if (len(mat) / len(qw)) >= settings.MIN_CONTENT_WORD_OVERLAP or sc >= settings.RELEVANCE_CONFIDENCE_THRESHOLD:
                valid_chunks.append((chk, sc))

        if not valid_chunks:
            return False, []
        return True, valid_chunks

    retrieval_latency_ms = 0.0
    embedding_latency_ms = 0.0

    try:
        if is_compound:
            sub_evaluations = []
            for sq in sub_questions:
                is_sup, sq_chunks = evaluate_subquestion_support(sq)
                retrieval_latency_ms += getattr(retrieval_service, "last_retrieval_latency_ms", 0.0)
                embedding_latency_ms += getattr(retrieval_service, "last_embedding_latency_ms", 0.0)
                sub_evaluations.append((sq, is_sup, sq_chunks))

            supported_subs = [(sq, chks) for sq, is_sup, chks in sub_evaluations if is_sup]
            unsupported_subs = [sq for sq, is_sup, _ in sub_evaluations if not is_sup]

            if not supported_subs:
                overall_status = "insufficient_context"
                retrieved_results = []
            elif not unsupported_subs:
                overall_status = "supported"
                seen_chunk_ids = set()
                combined_chunks = []
                for _, chks in supported_subs:
                    for chk, sc in chks:
                        if chk.chunk_id not in seen_chunk_ids:
                            seen_chunk_ids.add(chk.chunk_id)
                            combined_chunks.append((chk, sc))
                retrieved_results = combined_chunks
            else:
                overall_status = "partially_supported"
                seen_chunk_ids = set()
                combined_chunks = []
                for _, chks in supported_subs:
                    for chk, sc in chks:
                        if chk.chunk_id not in seen_chunk_ids:
                            seen_chunk_ids.add(chk.chunk_id)
                            combined_chunks.append((chk, sc))
                retrieved_results = combined_chunks
        else:
            retrieved_results = retrieval_service.retrieve(
                document_id=request.document_id,
                query=request.question,
                top_k=request.top_k
            )
            retrieval_latency_ms = getattr(retrieval_service, "last_retrieval_latency_ms", 0.0)
            embedding_latency_ms = getattr(retrieval_service, "last_embedding_latency_ms", 0.0)
            overall_status = "supported" if retrieved_results else "insufficient_context"
            supported_subs = [(request.question, retrieved_results)] if retrieved_results else []
            unsupported_subs = [] if retrieved_results else [request.question]
    except EmbeddingDimensionMismatchError as dim_err:
        logger.error(f"[{request_id}] Embedding dimension mismatch: {str(dim_err)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(dim_err),
            headers={"X-Error-Category": "embedding_dimension_mismatch"}
        )
    except Exception as e:
        logger.error(f"[{request_id}] Retrieval error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving relevant document passages."
        )

    # If no chunks passed similarity / support evaluation
    if not retrieved_results or overall_status == "insufficient_context":
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

        refusal_answer = "I couldn't find enough information in the uploaded document to answer this question."
        if conv_service and active_conversation_id:
            try:
                conv_service.add_message(
                    conversation_id=active_conversation_id,
                    role="assistant",
                    content=refusal_answer,
                    intent="unsupported",
                    evidence_state="insufficient_context",
                    sources=[],
                    telemetry=telemetry
                )
            except Exception as e:
                logger.error(f"[{request_id}] Failed to persist assistant refusal message: {str(e)}")

        audit_trace_data = {
            "request_id": request_id,
            "query": request.question,
            "iteration_count": 1,
            "selected_intent": "unsupported" if not is_compound else "compound_query",
            "selected_tools": ["search_document_evidence"],
            "tool_executions": [],
            "final_evidence_state": "insufficient_context",
            "answer_derivation_type": "refusal"
        }

        return ApiResponse(
            success=True,
            message="Question answered",
            data=ChatResponse(
                answer=refusal_answer,
                sources=[],
                confidence="insufficient_context",
                request_id=request_id,
                telemetry=telemetry,
                conversation_id=active_conversation_id,
                audit_trace=audit_trace_data
            ).model_dump()
        )

    # 6. Hard limit: validate retrieved context character budget
    total_context_chars = sum(len(chunk.text) for chunk, _ in retrieved_results)
    if total_context_chars > settings.MAX_CONTEXT_CHARS:
        total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            document_id=request.document_id,
            status="rejected",
            error_category="context_limit_exceeded",
            total_latency_ms=round(total_latency_ms, 2),
            retrieval_latency_ms=round(retrieval_latency_ms, 2),
            embedding_latency_ms=round(embedding_latency_ms, 2),
            retrieved_chunks_count=len(retrieved_results),
            token_usage_type="unknown"
        )
        record_chat_telemetry(telemetry)
        logger.warning(f"[{request_id}] Context rejected: total context chars ({total_context_chars}) > {settings.MAX_CONTEXT_CHARS}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Retrieved context size ({total_context_chars} characters) exceeds maximum allowed limit of {settings.MAX_CONTEXT_CHARS} characters. [context_limit_exceeded]",
            headers={"X-Error-Category": "context_limit_exceeded"}
        )

    # 7. Create verifiable citations
    citations = citation_service.create_citations(retrieved_results)

    # 8. Generate grounded response with bounded prompt token budget
    t_llm_call_start = time.perf_counter()
    try:
        if is_compound and overall_status == "partially_supported":
            # Generate answer for supported components only
            supported_answers = []
            sub_llm_responses = []
            for sq, sq_chunks in supported_subs:
                sq_context = [
                    f"[Section: {chunk.section} | Page: {chunk.page_number}]\n{chunk.text}"
                    for chunk, _ in sq_chunks
                ]
                sub_res = llm_service.generate_answer(
                    question=sq,
                    context_chunks=sq_context,
                    history=effective_history
                )
                sub_llm_responses.append(sub_res)
                sub_text = sub_res.content if isinstance(sub_res, LLMResponse) else str(sub_res)
                supported_answers.append(sub_text)

            unsupported_notes = [
                f"{clean_subquery_topic(un_sq)}: not found in the provided document."
                for un_sq in unsupported_subs
            ]

            full_answer_parts = supported_answers + unsupported_notes
            answer_text = "\n\n".join(full_answer_parts)

            # Aggregate telemetry tokens/latencies across sub-calls
            measured_llm_latency_ms = max(0.0, (time.perf_counter() - t_llm_call_start) * 1000.0)
            llm_latency_ms = sum(getattr(r, "latency_ms", 0.0) for r in sub_llm_responses) or measured_llm_latency_ms
            input_tokens = sum(r.input_tokens for r in sub_llm_responses if r.input_tokens is not None) if all(r.input_tokens is not None for r in sub_llm_responses) else None
            output_tokens = sum(r.output_tokens for r in sub_llm_responses if r.output_tokens is not None) if all(r.output_tokens is not None for r in sub_llm_responses) else None
            total_tokens = sum(r.total_tokens for r in sub_llm_responses if r.total_tokens is not None) if all(r.total_tokens is not None for r in sub_llm_responses) else None
            token_usage_type = sub_llm_responses[0].token_usage_type if sub_llm_responses else "estimated"
            est_input_tokens = sum(r.estimated_input_tokens or 0 for r in sub_llm_responses) or None
            est_output_tokens = sum(r.estimated_output_tokens or 0 for r in sub_llm_responses) or None
            est_total_tokens = ((est_input_tokens or 0) + (est_output_tokens or 0)) if (est_input_tokens or est_output_tokens) else None
            est_method = sub_llm_responses[0].estimation_method if sub_llm_responses else None
            llm_provider = sub_llm_responses[0].provider if sub_llm_responses else settings.LLM_PROVIDER
            llm_model = sub_llm_responses[0].model if sub_llm_responses else settings.LLM_MODEL
            confidence = "partially_supported"

        else:
            context_chunks = [
                f"[Section: {chunk.section} | Page: {chunk.page_number}]\n{chunk.text}"
                for chunk, _ in retrieved_results
            ]
            llm_result = llm_service.generate_answer(
                question=request.question,
                context_chunks=context_chunks,
                history=effective_history
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

            confidence = overall_status
            if "couldn't find enough information" in answer_text.lower():
                confidence = "insufficient_context"
                citations = []

    except TokenBudgetExceededError as tbe:
        total_latency_ms = max(0.0, (time.perf_counter() - t_request_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            document_id=request.document_id,
            status="rejected",
            error_category=tbe.error_category,
            total_latency_ms=round(total_latency_ms, 2),
            retrieval_latency_ms=round(retrieval_latency_ms, 2),
            embedding_latency_ms=round(embedding_latency_ms, 2),
            retrieved_chunks_count=len(retrieved_results),
            token_usage_type="unknown"
        )
        record_chat_telemetry(telemetry)
        logger.warning(f"[{request_id}] Token budget rejected: {tbe.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{tbe.message} [{tbe.error_category}]",
            headers={"X-Error-Category": tbe.error_category}
        )
    except Exception as e:
        logger.error(f"[{request_id}] LLM generation failure: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate answer from language model provider."
        )

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

    if conv_service and active_conversation_id:
        try:
            conv_service.add_message(
                conversation_id=active_conversation_id,
                role="assistant",
                content=answer_text,
                intent="specific_fact" if not is_compound else "compound_query",
                evidence_state=confidence,
                sources=citations,
                telemetry=telemetry
            )
        except Exception as e:
            logger.error(f"[{request_id}] Failed to persist assistant response message: {str(e)}")

    audit_trace_fallback = {
        "request_id": request_id,
        "query": request.question,
        "iteration_count": 2 if is_compound else 1,
        "selected_intent": "compound_query" if is_compound else "evidence_search",
        "selected_tools": ["search_document_evidence"],
        "tool_executions": [],
        "final_evidence_state": confidence,
        "answer_derivation_type": "grounded_synthesis"
    }

    return ApiResponse(
        success=True,
        message="Question answered",
        data=ChatResponse(
            answer=answer_text,
            sources=citations,
            confidence=confidence,
            request_id=request_id,
            telemetry=telemetry,
            conversation_id=active_conversation_id,
            audit_trace=audit_trace_fallback
        ).model_dump()
    )

