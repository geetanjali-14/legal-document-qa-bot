"""Multi-Document Isolated Comparison Tool (P2-MDOC-01).

Implements true multi-document comparison:
- Isolated retrieval namespaces per document ID
- Independent evidence retrieval across documents
- Aligned comparison matrix with document-specific citations
- Explicit distinction between: same, different, present_only_in_a, present_only_in_b, insufficient_evidence
- Absolute zero cross-contamination
"""
import time
from typing import List, Dict, Any, Optional
from app.services.tools.evidence_tool import EvidenceRetrievalTool
from app.services.document_service import DocumentService
from app.models.structure import MultiDocComparisonResult, ComparisonRow
from app.models.agent import UncertaintyState
from app.core.logging import logger


class MultiDocumentComparisonTool:
    """Tool for comparing legal terms and provisions across two distinct documents."""

    def __init__(
        self,
        document_service: DocumentService,
        evidence_tool: EvidenceRetrievalTool
    ):
        self.document_service = document_service
        self.evidence_tool = evidence_tool

    def compare_documents(
        self,
        doc_a_id: str,
        doc_b_id: str,
        topics: List[str]
    ) -> MultiDocComparisonResult:
        """
        Compare doc_a and doc_b across specified legal topics.
        Executes isolated evidence queries for each document independently.
        """
        t_start = time.perf_counter()

        doc_a_meta = self.document_service.get_document(doc_a_id)
        doc_b_meta = self.document_service.get_document(doc_b_id)

        doc_a_name = doc_a_meta.original_filename if doc_a_meta else doc_a_id
        doc_b_name = doc_b_meta.original_filename if doc_b_meta else doc_b_id

        rows: List[ComparisonRow] = []

        for topic in topics:
            # 1. Isolated query for Document A
            ev_a = self.evidence_tool.search_document_evidence(
                document_ids=[doc_a_id],
                query=topic,
                top_k=2
            )

            # 2. Isolated query for Document B
            ev_b = self.evidence_tool.search_document_evidence(
                document_ids=[doc_b_id],
                query=topic,
                top_k=2
            )

            # 3. Align and classify evidence
            has_a = len(ev_a.items) > 0 and ev_a.evidence_state != UncertaintyState.INSUFFICIENT_EVIDENCE
            has_b = len(ev_b.items) > 0 and ev_b.evidence_state != UncertaintyState.INSUFFICIENT_EVIDENCE

            text_a = ev_a.items[0].text if has_a else "No explicit provision found."
            cite_a = {
                "document_id": doc_a_id,
                "document_name": doc_a_name,
                "page": ev_a.items[0].page_number if has_a else None,
                "section": ev_a.items[0].section if has_a else None,
                "chunk_id": ev_a.items[0].chunk_id if has_a else None
            } if has_a else None

            text_b = ev_b.items[0].text if has_b else "No explicit provision found."
            cite_b = {
                "document_id": doc_b_id,
                "document_name": doc_b_name,
                "page": ev_b.items[0].page_number if has_b else None,
                "section": ev_b.items[0].section if has_b else None,
                "chunk_id": ev_b.items[0].chunk_id if has_b else None
            } if has_b else None

            # Determine comparison status
            if has_a and has_b:
                # Compare similarity of texts
                words_a = set(text_a.lower().split())
                words_b = set(text_b.lower().split())
                overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
                status = "same" if overlap > 0.75 else "different"
            elif has_a and not has_b:
                status = "present_only_in_a"
            elif not has_a and has_b:
                status = "present_only_in_b"
            else:
                status = "insufficient_evidence"

            rows.append(
                ComparisonRow(
                    topic=topic,
                    status=status,
                    doc_a_evidence=text_a[:1000],
                    doc_a_citation=cite_a,
                    doc_b_evidence=text_b[:1000],
                    doc_b_citation=cite_b
                )
            )

        latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)

        # Summary text
        summary = (
            f"Comparison completed across {len(topics)} topics between "
            f"'{doc_a_name}' and '{doc_b_name}'."
        )

        return MultiDocComparisonResult(
            doc_a_id=doc_a_id,
            doc_b_id=doc_b_id,
            doc_a_name=doc_a_name,
            doc_b_name=doc_b_name,
            topics=topics,
            rows=rows,
            summary=summary,
            latency_ms=round(latency_ms, 2)
        )

