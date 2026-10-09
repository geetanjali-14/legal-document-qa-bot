"""Evidence Retrieval Tool (P1-TOOL-03).

Encapsulates vector search, document namespace isolation, section filtering,
and the semantic confidence gate (OPT-003) into a reusable tool.
"""
import time
from typing import List, Optional, Any
from app.models.agent import EvidenceResult, EvidenceItem, UncertaintyState
from app.services.retrieval_service import RetrievalService
from app.core.config import settings
from app.core.logging import logger


class EvidenceRetrievalTool:
    def __init__(self, retrieval_service: RetrievalService, rag_provider: Optional[Any] = None):
        self.retrieval_service = retrieval_service
        self.rag_provider = rag_provider

    def search_document_evidence(
        self,
        document_ids: List[str],
        query: str,
        top_k: Optional[int] = None,
        section_filter: Optional[str] = None
    ) -> EvidenceResult:
        """
        Executes bounded, grounded evidence retrieval across specified document namespaces.
        Applies OPT-003 confidence gate and retains provenance metadata.
        """
        t_start = time.perf_counter()
        k = top_k or settings.TOP_K

        all_items: List[EvidenceItem] = []

        for doc_id in document_ids:
            if self.rag_provider is not None and hasattr(self.rag_provider, "retrieve"):
                retrieved_chunks = self.rag_provider.retrieve(
                    document_id=doc_id,
                    query=query,
                    top_k=k
                )
                for r_chunk in retrieved_chunks:
                    if section_filter and r_chunk.section:
                        if section_filter.lower() not in r_chunk.section.lower():
                            continue
                    all_items.append(
                        EvidenceItem(
                            document_id=r_chunk.document_id,
                            chunk_id=r_chunk.chunk_id,
                            page_number=r_chunk.page_number,
                            section=r_chunk.section or "General",
                            score=round(float(r_chunk.score), 4),
                            text=r_chunk.text,
                            document_name=r_chunk.document_name
                        )
                    )
            else:
                raw_results = self.retrieval_service.retrieve(
                    document_id=doc_id,
                    query=query,
                    top_k=k
                )

                for chunk, score in raw_results:
                    # Apply section filter if requested
                    if section_filter and chunk.section:
                        if section_filter.lower() not in chunk.section.lower():
                            continue

                    all_items.append(
                        EvidenceItem(
                            document_id=chunk.document_id,
                            chunk_id=chunk.chunk_id,
                            page_number=chunk.page_number,
                            section=chunk.section or "General",
                            score=round(float(score), 4),
                            text=chunk.text,
                            document_name=chunk.document_name
                        )
                    )

        # Sort all items by relevance score descending
        all_items.sort(key=lambda x: x.score, reverse=True)
        bounded_items = all_items[:k]

        latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)

        # Determine evidence state
        if not bounded_items:
            evidence_state = UncertaintyState.INSUFFICIENT_EVIDENCE
        else:
            top_score = bounded_items[0].score
            if top_score >= settings.RELEVANCE_CONFIDENCE_THRESHOLD:
                evidence_state = UncertaintyState.SUPPORTED
            elif top_score >= settings.SIMILARITY_THRESHOLD:
                evidence_state = UncertaintyState.PARTIALLY_SUPPORTED
            else:
                evidence_state = UncertaintyState.INSUFFICIENT_EVIDENCE

        logger.info(
            f"[EvidenceRetrievalTool] Retrieved {len(bounded_items)} items across docs={document_ids} "
            f"in {latency_ms:.2f}ms (state={evidence_state.value})"
        )

        return EvidenceResult(
            document_ids=document_ids,
            query=query,
            items=bounded_items,
            evidence_state=evidence_state,
            latency_ms=round(latency_ms, 2)
        )

    # Alias for compatibility
    retrieve_evidence = search_document_evidence

