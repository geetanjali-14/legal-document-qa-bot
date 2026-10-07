"""Controlled Intent Classification & Multi-Intent Router (P1-ROUT-01).

Routes incoming queries across 7 operational intents using deterministic regex/heuristics
first, with multi-intent decomposition and safe defaulting to EVIDENCE_SEARCH.
"""
import re
from typing import List, Dict, Any, Optional
from app.models.agent import IntentType, IntentRoutingResult
from app.core.logging import logger


# Deterministic regex patterns for METADATA intent
METADATA_PATTERNS = [
    r"\bhow\s+many\s+pages\b",
    r"\bpage\s+count\b",
    r"\bnumber\s+of\s+pages\b",
    r"\bhow\s+many\s+chunks\b",
    r"\bchunk\s+count\b",
    r"\bfile\s+size\b",
    r"\bhow\s+large\s+is\s+(?:the|this)\s+file\b",
    r"\bwhat\s+is\s+the\s+(?:file\s+)?size\b",
    r"\bwhat\s+is\s+the\s+name\s+of\s+(?:this|the)\s+(?:file|document)\b",
    r"\bfilename\b",
    r"\bwhat\s+is\s+(?:the\s+)?filename\b",
    r"\bwhen\s+was\s+(?:this|it|the\s+document)\s+uploaded\b",
    r"\bupload\s+date\b",
    r"\bupload\s+time\b",
    r"\bcontent\s+hash\b",
    r"\bsha-?256\b",
]

# Deterministic regex patterns for DOCUMENT_OVERVIEW intent
OVERVIEW_PATTERNS = [
    r"\bwhat\s+is\s+this\s+document\s+about\b",
    r"\bgive\s+me\s+an\s+overview\b",
    r"\bsummarize\s+(?:this|the)\s+document\b",
    r"\bdocument\s+summary\b",
    r"\bexecutive\s+summary\b",
    r"\bwho\s+are\s+the\s+parties\b",
    r"\bwhat\s+parties\s+are\s+involved\b",
    r"\bparties\s+to\s+this\s+(?:agreement|contract|document)\b",
    r"\bwhat\s+type\s+of\s+(?:agreement|contract|document)\s+is\s+this\b",
    r"\bwhat\s+kind\s+of\s+(?:agreement|contract|document)\b",
    r"\bmajor\s+topics\b",
    r"\bkey\s+topics\b",
    r"\bmain\s+topics\b",
    r"\bpurpose\s+of\s+this\s+(?:agreement|contract|document)\b",
]

# Deterministic regex patterns for STRUCTURE_NAVIGATION intent
STRUCTURE_PATTERNS = [
    r"\bwhat\s+sections\s+(?:are\s+in|does\s+this)\b",
    r"\btable\s+of\s+contents\b",
    r"\blist\s+(?:all\s+)?(?:the\s+)?sections\b",
    r"\bshow\s+me\s+section\s+[0-9IVXLCDM\.]+\b",
    r"\bshow\s+me\s+clause\s+[0-9IVXLCDM\.\(\)a-z]+\b",
    r"\bwhat\s+does\s+(?:section|clause|article)\s+[0-9IVXLCDM\.\(\)a-z]+\s+cover\b",
    r"\bwhat\s+is\s+(?:clause|section|article)\s+[0-9IVXLCDM\.\(\)a-z]+\b",
    r"\boutline\s+of\s+(?:the\s+)?document\b",
    r"\bstructure\s+of\s+(?:the\s+)?document\b",
]

# Deterministic regex patterns for MULTI_DOCUMENT_COMPARE intent
COMPARE_PATTERNS = [
    r"\bcompare\s+(?:both|the|these)?\s*documents\b",
    r"\bcompare\s+(?:document|contract)\s+[A-Za-z0-9_-]+\s+(?:and|with|to)\s+[A-Za-z0-9_-]+\b",
    r"\bdifferences\s+between\s+(?:the\s+)?(?:two|both|documents)\b",
    r"\bcompare\s+the\s+termination\s+terms\b",
]

# Patterns for CROSS_SECTION_ANALYSIS intent
CROSS_SECTION_PATTERNS = [
    r"\bacross\s+sections?\b",
    r"\bconflict\s+between\s+section\b",
    r"\bcompare\s+section\s+.*and\s+section\b",
    r"\bhow\s+does\s+section\s+.*relate\s+to\s+section\b",
]


class IntentRouter:
    """
    Controlled hybrid router classifying user inquiries across 7 operational intents.
    Supports multi-intent decomposition without unconstrained LLM dependencies.
    """

    def __init__(self):
        self._meta_regex = [re.compile(p, re.IGNORECASE) for p in METADATA_PATTERNS]
        self._overview_regex = [re.compile(p, re.IGNORECASE) for p in OVERVIEW_PATTERNS]
        self._structure_regex = [re.compile(p, re.IGNORECASE) for p in STRUCTURE_PATTERNS]
        self._compare_regex = [re.compile(p, re.IGNORECASE) for p in COMPARE_PATTERNS]
        self._cross_regex = [re.compile(p, re.IGNORECASE) for p in CROSS_SECTION_PATTERNS]

    def route_query(self, query: str) -> IntentRoutingResult:
        """
        Classifies intent and identifies multi-intent composition.
        """
        cleaned_query = query.strip()
        matched_intents: List[IntentType] = []
        sub_intents: List[Dict[str, Any]] = []

        # Check for Metadata matches
        matched_meta_attr = self._detect_metadata_attribute(cleaned_query)
        has_metadata = bool(matched_meta_attr) or any(rx.search(cleaned_query) for rx in self._meta_regex)
        if has_metadata:
            matched_intents.append(IntentType.METADATA)
            sub_intents.append({
                "intent": IntentType.METADATA.value,
                "attribute": matched_meta_attr or "general"
            })

        # Check for Overview matches
        has_overview = any(rx.search(cleaned_query) for rx in self._overview_regex)
        if has_overview:
            matched_intents.append(IntentType.DOCUMENT_OVERVIEW)
            sub_intents.append({
                "intent": IntentType.DOCUMENT_OVERVIEW.value,
                "aspect": self._detect_overview_aspect(cleaned_query)
            })

        # Check for Structure Navigation
        has_structure = any(rx.search(cleaned_query) for rx in self._structure_regex)
        if has_structure:
            matched_intents.append(IntentType.STRUCTURE_NAVIGATION)
            sub_intents.append({
                "intent": IntentType.STRUCTURE_NAVIGATION.value
            })

        # Check for Multi-Document Compare
        has_compare = any(rx.search(cleaned_query) for rx in self._compare_regex)
        if has_compare:
            matched_intents.append(IntentType.MULTI_DOCUMENT_COMPARE)
            sub_intents.append({
                "intent": IntentType.MULTI_DOCUMENT_COMPARE.value
            })

        # Check for Cross-Section Analysis
        has_cross = any(rx.search(cleaned_query) for rx in self._cross_regex)
        if has_cross:
            matched_intents.append(IntentType.CROSS_SECTION_ANALYSIS)
            sub_intents.append({
                "intent": IntentType.CROSS_SECTION_ANALYSIS.value
            })

        # Handle multi-intent composition (e.g. Overview + Metadata)
        if len(matched_intents) > 1:
            primary = matched_intents[0]
            logger.info(f"[IntentRouter] Multi-intent detected for query '{cleaned_query}': {[i.value for i in matched_intents]}")
            return IntentRoutingResult(
                primary_intent=primary,
                intents=matched_intents,
                confidence=0.95,
                is_multi_intent=True,
                sub_intents=sub_intents,
                reasoning="Composite query matching multiple operational intents."
            )

        if len(matched_intents) == 1:
            logger.info(f"[IntentRouter] Single-intent classified: {matched_intents[0].value}")
            return IntentRoutingResult(
                primary_intent=matched_intents[0],
                intents=matched_intents,
                confidence=0.98,
                is_multi_intent=False,
                sub_intents=sub_intents,
                reasoning=f"Matched heuristic patterns for {matched_intents[0].value}."
            )

        # Unsupported or pure out-of-domain non-legal queries
        unsupported_markers = [
            r"\bwrite\s+a\s+python\s+script\b",
            r"\bwrite\s+code\b",
            r"\btell\s+me\s+a\s+joke\b",
            r"\bweather\s+in\b",
            r"\bwho\s+is\s+the\s+president\b",
        ]
        if any(re.search(p, cleaned_query, re.IGNORECASE) for p in unsupported_markers):
            return IntentRoutingResult(
                primary_intent=IntentType.UNSUPPORTED,
                intents=[IntentType.UNSUPPORTED],
                confidence=0.95,
                is_multi_intent=False,
                sub_intents=[{"intent": IntentType.UNSUPPORTED.value}],
                reasoning="Query falls outside legal document domain."
            )

        # Default toward EVIDENCE_SEARCH for substantive questions
        return IntentRoutingResult(
            primary_intent=IntentType.EVIDENCE_SEARCH,
            intents=[IntentType.EVIDENCE_SEARCH],
            confidence=0.85,
            is_multi_intent=False,
            sub_intents=[{"intent": IntentType.EVIDENCE_SEARCH.value, "query": cleaned_query}],
            reasoning="Defaulted substantive legal question to EVIDENCE_SEARCH."
        )

    def _detect_metadata_attribute(self, query: str) -> Optional[str]:
        q = query.lower()
        if "page" in q:
            return "page_count"
        if "filename" in q or "name of this" in q or "file name" in q:
            return "filename"
        if "size" in q or "large" in q or "bytes" in q:
            return "file_size"
        if "chunk" in q:
            return "chunk_count"
        if "upload" in q:
            return "created_at"
        if "hash" in q or "sha" in q:
            return "content_hash"
        return None

    def _detect_overview_aspect(self, query: str) -> str:
        q = query.lower()
        if "parties" in q or "who are" in q:
            return "parties"
        if "type of agreement" in q or "kind of agreement" in q:
            return "document_type"
        if "topics" in q:
            return "topics"
        return "summary"

