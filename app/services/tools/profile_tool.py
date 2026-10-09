"""Document Overview & Profile Tool (P1-TOOL-02).

Answers high-level contract questions (parties, agreement type, executive summary, major topics)
grounded directly in extracted document chunks and cached against the document content hash.
"""
import re
from typing import Optional, List, Set
from app.models.agent import DocumentProfileResult
from app.services.document_service import DocumentService
from app.persistence.repository import ConversationRepository
from app.core.logging import logger


class DocumentProfileTool:
    def __init__(self, document_service: DocumentService, repository: ConversationRepository):
        self.document_service = document_service
        self.repository = repository

    def get_document_profile(self, document_id: str) -> Optional[DocumentProfileResult]:
        """
        Retrieves or synthesizes a grounded DocumentProfileResult.
        Validates content_hash against the document to guarantee cache freshness.
        """
        doc = self.document_service.get_document(document_id)
        if not doc:
            logger.warning(f"[DocumentProfileTool] Document not found: {document_id}")
            return None

        # Check durable database cache
        cached_model = self.repository.get_document_profile(document_id)
        if cached_model and cached_model.content_hash == (doc.content_hash or ""):
            return DocumentProfileResult(
                document_id=cached_model.document_id,
                content_hash=cached_model.content_hash,
                document_type=cached_model.document_type,
                parties=list(cached_model.parties or []),
                effective_date=cached_model.effective_date,
                executive_summary=cached_model.executive_summary,
                major_topics=list(cached_model.major_topics or []),
                source_pages=list(cached_model.source_pages or []),
                source_sections=list(cached_model.source_sections or []),
                generated_at=cached_model.created_at.isoformat()
            )

        # Generate grounded profile directly from document chunks
        profile = self._synthesize_grounded_profile(doc)
        if profile:
            self.repository.save_document_profile(
                document_id=profile.document_id,
                content_hash=profile.content_hash,
                document_type=profile.document_type,
                parties=profile.parties,
                effective_date=profile.effective_date,
                executive_summary=profile.executive_summary,
                major_topics=profile.major_topics,
                source_pages=profile.source_pages,
                source_sections=profile.source_sections
            )
        return profile

    def _synthesize_grounded_profile(self, doc) -> Optional[DocumentProfileResult]:
        """
        Extracts document type, parties, effective date, and key sections deterministically
        from early and structural chunks.
        """
        chunks = self.document_service.get_document_chunks(doc.document_id)
        if not chunks:
            return None

        # Extract preamble text (typically chunks from page 1)
        p1_chunks = [c for c in chunks if c.page_number == 1]
        preamble_text = "\n".join(c.text for c in p1_chunks) if p1_chunks else chunks[0].text

        # Detect Document Type
        doc_type = "Legal Agreement"
        title_match = re.search(r"^[A-Z\s]{4,}(?:AGREEMENT|CONTRACT|POLICY|TERMS|PLAN|MEMORANDUM)", preamble_text, re.MULTILINE)
        if title_match:
            doc_type = title_match.group(0).strip().title()
        elif "service agreement" in preamble_text.lower():
            doc_type = "Master Services Agreement"
        elif "non-disclosure" in preamble_text.lower() or "confidentiality" in preamble_text.lower():
            doc_type = "Non-Disclosure Agreement"

        # Detect Parties
        parties: List[str] = []
        party_matches = re.findall(r'\"?([A-Za-z0-9\s,\.]+?)\"?\s*\((?:the\s+)?\"?([A-Za-z]+)\"?\)', preamble_text)
        if party_matches:
            for full_p, alias in party_matches:
                p_clean = full_p.strip(" \t\n\r\"'").replace("between ", "")
                if len(p_clean) > 2:
                    parties.append(f"{p_clean} ({alias})")
        else:
            between_match = re.search(r'between\s+([A-Za-z0-9\s,\.]+?)\s+and\s+([A-Za-z0-9\s,\.]+?)(?:,|\.|\(|$)', preamble_text, re.IGNORECASE)
            if between_match:
                parties = [between_match.group(1).strip(" \t\n\r\"'"), between_match.group(2).strip(" \t\n\r\"'")]

        # Detect Effective Date
        effective_date = None
        date_match = re.search(r'effective\s+(?:as\s+of\s+)?([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})', preamble_text, re.IGNORECASE)
        if date_match:
            effective_date = date_match.group(1).strip()

        # Collect Distinct Major Sections
        sections_set: Set[str] = set()
        source_pages: Set[int] = set()
        for c in chunks:
            source_pages.add(c.page_number)
            if c.section and c.section != "General":
                sections_set.add(c.section.strip())

        major_sections = sorted(list(sections_set))
        if not major_sections:
            major_sections = ["General Provisions"]

        # Synthesize Executive Summary grounded in verified metadata
        parties_str = " and ".join(parties) if parties else "the designated parties"
        date_str = f" entered into on {effective_date}" if effective_date else ""
        exec_summary = (
            f"This document is a {doc_type}{date_str} between {parties_str}. "
            f"It encompasses {doc.page_count} pages and governs operational commitments including "
            f"{', '.join(major_sections[:4])}."
        )

        from datetime import datetime, timezone
        return DocumentProfileResult(
            document_id=doc.document_id,
            content_hash=doc.content_hash or "hash_unknown",
            document_type=doc_type,
            parties=parties,
            effective_date=effective_date,
            executive_summary=exec_summary,
            major_topics=major_sections,
            source_pages=sorted(list(source_pages)),
            source_sections=major_sections,
            generated_at=datetime.now(timezone.utc).isoformat()
        )

    def format_overview_answer(self, profile: DocumentProfileResult, aspect: Optional[str] = None) -> str:
        """
        Formats structured, grounded answers for document overview queries.
        """
        if aspect == "parties":
            if profile.parties:
                return f"The identified parties to this {profile.document_type} are:\n" + "\n".join(f"- {p}" for p in profile.parties)
            return f"The document identifies general parties under a {profile.document_type}, but distinct company names were not explicitly tagged."
        elif aspect == "document_type":
            return f"This document is a {profile.document_type}."
        elif aspect == "topics":
            return f"The major sections and topics covered in this document are:\n" + "\n".join(f"- {t}" for t in profile.major_topics)
        else:
            parties_line = f"Parties: {', '.join(profile.parties)}\n" if profile.parties else ""
            date_line = f"Effective Date: {profile.effective_date}\n" if profile.effective_date else ""
            topics_line = f"Key Sections: {', '.join(profile.major_topics[:6])}\n" if profile.major_topics else ""
            return (
                f"**Document Overview: {profile.document_type}**\n\n"
                f"{profile.executive_summary}\n\n"
                f"{parties_line}"
                f"{date_line}"
                f"{topics_line}"
            ).strip()
