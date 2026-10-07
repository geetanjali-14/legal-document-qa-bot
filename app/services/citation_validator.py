"""Citation Validator (P1 Grounding & Verification).

Ensures all citations strictly map to verified evidence chunks, valid document IDs,
and valid pages, eliminating hallucinated references.
"""
from typing import List, Tuple
from app.models.chat import Citation
from app.models.agent import EvidenceItem
from app.core.logging import logger


class CitationValidator:
    @staticmethod
    def validate_citations(
        citations: List[Citation],
        evidence_items: List[EvidenceItem]
    ) -> Tuple[List[Citation], bool]:
        """
        Validates that every citation originates from verified evidence.
        Filters out citations with unknown chunk_ids or mismatched documents.
        Returns: (validated_citations, is_completely_grounded)
        """
        if not citations:
            return [], True

        valid_chunk_map = {item.chunk_id: item for item in evidence_items}
        validated: List[Citation] = []

        for cit in citations:
            matched_item = valid_chunk_map.get(cit.chunk_id)
            if not matched_item:
                logger.warning(f"[CitationValidator] Rejected unverified citation chunk_id={cit.chunk_id}")
                continue

            if cit.document_id != matched_item.document_id:
                logger.warning(f"[CitationValidator] Rejected citation with document mismatch: {cit.document_id} vs {matched_item.document_id}")
                continue

            # Ensure page and snippet fidelity
            clean_snippet = cit.snippet.strip()
            if len(clean_snippet) > 250:
                clean_snippet = clean_snippet[:247] + "..."

            validated.append(
                Citation(
                    document_id=matched_item.document_id,
                    document_name=matched_item.document_name or cit.document_name,
                    page_number=matched_item.page_number,
                    section=matched_item.section or cit.section,
                    chunk_id=matched_item.chunk_id,
                    snippet=clean_snippet,
                    relevance_score=matched_item.score
                )
            )

        is_grounded = len(validated) == len(citations)
        return validated, is_grounded

