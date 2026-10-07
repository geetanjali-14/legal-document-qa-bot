"""Deterministic Section & Structure Tool (P2-TOOL-04).

Supports:
- Table of contents extraction
- Exact section and clause lookup (e.g., 'Section 8', '8.2(b)')
- Parent/child structural hierarchy navigation
- Deterministic execution consuming 0 LLM tokens
"""
import time
import re
from typing import Optional, Dict, Any, List
from app.services.document_service import DocumentService
from app.models.structure import StructureResult, SectionNode
from app.core.logging import logger


class SectionStructureTool:
    """Tool for deterministic section and structure exploration."""

    def __init__(self, document_service: DocumentService):
        self.document_service = document_service

    def get_section_structure(
        self,
        document_id: str,
        section_query: Optional[str] = None
    ) -> StructureResult:
        """
        Query table of contents or specific section by ID or title.
        Returns: StructureResult (0 LLM tokens).
        """
        t_start = time.perf_counter()
        structure = self.document_service.get_document_structure(document_id)

        if not structure:
            latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
            return StructureResult(
                document_id=document_id,
                total_sections=0,
                table_of_contents=[],
                matched_section=None,
                latency_ms=round(latency_ms, 2)
            )

        # Build clean table of contents
        toc: List[Dict[str, Any]] = []
        for node in structure.nodes:
            toc.append(self._serialize_node(node))

        matched_dict = None
        if section_query:
            matched_dict = self._lookup_section(structure, section_query)

        latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        return StructureResult(
            document_id=document_id,
            total_sections=len(structure.flat_sections),
            table_of_contents=toc,
            matched_section=matched_dict,
            latency_ms=round(latency_ms, 2)
        )

    def _lookup_section(self, structure: Any, query: str) -> Optional[Dict[str, Any]]:
        """Look up section by exact or normalized key."""
        clean_q = query.strip()
        # Direct lookup
        if clean_q.lower() in structure.flat_sections:
            return self._serialize_node(structure.flat_sections[clean_q.lower()])

        # Normalized lookup (stripping non-alphanumeric)
        norm_q = re.sub(r'[^a-z0-9]', '', clean_q.lower())
        if norm_q in structure.flat_sections:
            return self._serialize_node(structure.flat_sections[norm_q])

        # Partial matching on section_id or title
        for key, node in structure.flat_sections.items():
            if (
                clean_q.lower() in node.title.lower()
                or clean_q.lower() in node.section_id.lower()
                or (node.raw_header and clean_q.lower() in node.raw_header.lower())
            ):
                return self._serialize_node(node)

        return None

    def _serialize_node(self, node: SectionNode) -> Dict[str, Any]:
        """Convert SectionNode into serialized dictionary."""
        return {
            "section_id": node.section_id,
            "title": node.title,
            "level": node.level,
            "parent_id": node.parent_id,
            "page_start": node.page_start,
            "page_end": node.page_end,
            "breadcrumb": node.breadcrumb,
            "text_content": (node.text_content[:300] + "...") if node.text_content and len(node.text_content) > 300 else node.text_content,
            "subsections": [self._serialize_node(sub) for sub in node.subsections] if node.subsections else []
        }

