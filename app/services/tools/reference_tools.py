"""Cross-Reference Resolution & Definition Awareness Tools (P2-TOOL-05, P2-TOOL-05B).

Supports:
- Cross-reference resolution ("subject to Section 12.4") with isolated document scope
- Legal definition registry lookups ("Confidential Information means...")
- Distinguishing defined meanings from ordinary language
"""
import time
import re
from typing import Optional, Dict, Any, List
from app.services.document_service import DocumentService
from app.models.structure import CrossReference, LegalDefinition
from app.core.logging import logger


class CrossReferenceTool:
    """Tool for resolving internal cross-references within a single document scope."""

    def __init__(self, document_service: DocumentService):
        self.document_service = document_service

    def resolve_reference(
        self,
        document_id: str,
        target_reference: str
    ) -> Dict[str, Any]:
        """
        Locate and retrieve the target section/clause referenced inside the document.
        Scope is strictly isolated to document_id.
        """
        t_start = time.perf_counter()
        structure = self.document_service.get_document_structure(document_id)

        if not structure:
            return {
                "document_id": document_id,
                "found": False,
                "target": target_reference,
                "message": "Document structure not available.",
                "latency_ms": max(0.0, (time.perf_counter() - t_start) * 1000.0)
            }

        # Normalize target string (e.g. "Section 12.4" -> "12.4", "Annexure I" -> "I", "Schedule A" -> "A")
        clean_target = re.sub(r'^(?:Section|Article|Clause|Annexure|Schedule|Exhibit|Appendix)\s+', '', target_reference, flags=re.IGNORECASE).strip()
        norm_key = re.sub(r'[^a-z0-9]', '', clean_target.lower())

        target_node = structure.flat_sections.get(norm_key) or structure.flat_sections.get(clean_target.lower())

        # Check in schedules or annexures
        if not target_node:
            for item in getattr(structure, "schedules", []) + getattr(structure, "annexures", []):
                s_id = str(item.get("schedule_id") or item.get("annexure_id") or "").lower()
                if norm_key == s_id or clean_target.lower() in item.get("title", "").lower():
                    latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
                    return {
                        "document_id": document_id,
                        "found": True,
                        "target": target_reference,
                        "resolved_section_id": item.get("schedule_id") or item.get("annexure_id"),
                        "title": item.get("title"),
                        "page_start": item.get("page_number", 1),
                        "page_end": item.get("page_number", 1),
                        "breadcrumb": [item.get("title")],
                        "text_content": item.get("header") or item.get("title"),
                        "latency_ms": round(latency_ms, 2)
                    }

        if not target_node:
            # Check for partial matches
            for key, node in structure.flat_sections.items():
                if norm_key in key or clean_target.lower() in node.title.lower():
                    target_node = node
                    break

        latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)

        if target_node:
            return {
                "document_id": document_id,
                "found": True,
                "target": target_reference,
                "resolved_section_id": target_node.section_id,
                "title": target_node.title,
                "page_start": target_node.page_start,
                "page_end": target_node.page_end,
                "breadcrumb": target_node.breadcrumb,
                "text_content": target_node.text_content,
                "latency_ms": round(latency_ms, 2)
            }
        else:
            return {
                "document_id": document_id,
                "found": False,
                "target": target_reference,
                "message": f"Referenced section '{target_reference}' not found in document.",
                "latency_ms": round(latency_ms, 2)
            }


class DefinitionTool:
    """Tool for document-scoped legal definition registry lookups."""

    def __init__(self, document_service: DocumentService):
        self.document_service = document_service

    def lookup_definition(
        self,
        document_id: str,
        term: str
    ) -> Dict[str, Any]:
        """
        Look up a defined legal term in the document's definition registry.
        Scope is strictly isolated to document_id.
        """
        t_start = time.perf_counter()
        structure = self.document_service.get_document_structure(document_id)

        if not structure:
            return {
                "document_id": document_id,
                "found": False,
                "term": term,
                "latency_ms": max(0.0, (time.perf_counter() - t_start) * 1000.0)
            }

        clean_term = term.strip().lower()
        clean_norm = re.sub(r'[^a-z0-9]', '', clean_term)

        # 1. Exact or normalized registry lookup
        defn: Optional[LegalDefinition] = structure.definitions.get(clean_term)
        if not defn:
            for k, d in structure.definitions.items():
                if clean_norm == re.sub(r'[^a-z0-9]', '', k) or clean_term in k:
                    defn = d
                    break

        latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)

        if defn:
            return {
                "document_id": document_id,
                "found": True,
                "term": defn.term,
                "definition": defn.definition,
                "page_number": defn.page_number,
                "raw_snippet": defn.raw_snippet,
                "is_defined_term": True,
                "latency_ms": round(latency_ms, 2)
            }
        else:
            return {
                "document_id": document_id,
                "found": False,
                "term": term,
                "is_defined_term": False,
                "message": f"Term '{term}' is not a defined term in this agreement.",
                "latency_ms": round(latency_ms, 2)
            }

