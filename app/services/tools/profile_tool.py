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
        chunks = []
        if hasattr(self.document_service, "get_document_chunks"):
            ret = self.document_service.get_document_chunks(doc.document_id)
            if isinstance(ret, list):
                chunks = ret
        if not chunks and hasattr(self.document_service, "vector_store"):
            chunks_map = getattr(self.document_service.vector_store, "chunks_by_doc", {})
            if isinstance(chunks_map, dict):
                chunks = chunks_map.get(doc.document_id, [])

        if not chunks:
            return None

        # Extract preamble text (typically chunks from early pages)
        p1_chunks = [c for c in chunks if getattr(c, "page_number", None) == 1]
        preamble_text = "\n".join(c.text for c in p1_chunks) if p1_chunks else (chunks[0].text if hasattr(chunks[0], "text") else "")
        early_text = "\n".join(c.text for c in chunks[:10] if hasattr(c, "text"))

        # Detect Document Type
        doc_type = "Legal Agreement"
        title_match = re.search(r"^[A-Z\s]{4,}(?:AGREEMENT|CONTRACT|POLICY|TERMS|PLAN|MEMORANDUM)", preamble_text, re.MULTILINE)
        if title_match:
            doc_type = title_match.group(0).strip().title()
        elif "service agreement" in preamble_text.lower():
            doc_type = "Master Services Agreement"
        elif "non-disclosure" in preamble_text.lower() or "confidentiality" in preamble_text.lower():
            doc_type = "Non-Disclosure Agreement"
        else:
            # Fallback: check filename or top of document for explicit policy / agreement titles
            orig_fname = getattr(doc, "original_filename", "") or ""
            if "policy" in orig_fname.lower() or "policy" in early_text[:200].lower():
                policy_match = re.search(r"([A-Za-z0-9\s]{3,40}\bPolicy\b)", early_text[:300], re.IGNORECASE)
                if policy_match:
                    doc_type = policy_match.group(1).strip()
                else:
                    doc_type = "Policy Document"

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

        # Detect Effective Date across all chunks
        effective_date = None
        for c in chunks:
            c_txt = getattr(c, "text", "") or ""
            date_match = re.search(
                r'effective\s+(?:from|as\s+of|on)?\s*([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4}|[A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})',
                c_txt,
                re.IGNORECASE
            )
            if date_match:
                effective_date = date_match.group(1).strip()
                break

        # Grounded Purpose / Objective Statement extraction directly from document text
        purpose_stmt = None
        for c in chunks:
            c_txt = getattr(c, "text", "") or ""
            m_purp = re.search(
                r'(?:1\.\s*Purpose\s*[\n\r]+)?([^\n\r]+(?:purpose of this (?:policy|agreement|document|contract) is [^\.\n]+(?:\.[^\.\n]+)?\.?))',
                c_txt,
                re.IGNORECASE
            )
            if m_purp:
                purpose_stmt = m_purp.group(1).strip()
                # Ensure it ends with a period
                if not purpose_stmt.endswith('.'):
                    purpose_stmt += '.'
                break

        # Clean distinct major sections, removing noise, zero-width characters, month names, and generic headings
        generic_noise = {
            "general", "general provisions", "contents", "table of contents", "index",
            "office", "month of", "joining", "january", "february", "march", "april",
            "may", "june", "july", "august", "september", "october", "november", "december"
        }
        seen_sections = set()
        clean_major_sections = []
        source_pages: Set[int] = set()

        for c in chunks:
            source_pages.add(c.page_number)
            raw_sec = (c.section or "").strip()
            # Remove zero-width spaces and formatting artifacts
            sec = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', raw_sec).strip()
            sec = re.sub(r'[:;\.]+$', '', sec).strip()
            sec = ' '.join(sec.split())
            if not sec:
                continue
            sec_lower = sec.lower()
            if sec_lower in generic_noise or len(sec) < 3:
                continue
            # Filter out person name/director signatures from key sections list
            if "director" in sec_lower or "technologies pvt" in sec_lower:
                continue
            if sec_lower not in seen_sections:
                seen_sections.add(sec_lower)
                clean_major_sections.append(sec)

        if not clean_major_sections:
            clean_major_sections = ["General Provisions"]

        # Synthesize concise, natural overview strictly grounded in verified document data
        parties_str = " and ".join(parties) if parties else ""
        parties_clause = f" between {parties_str}" if parties_str else ""
        date_str = f", effective {effective_date}" if effective_date else ""
        page_str = f"{doc.page_count} page{'s' if doc.page_count != 1 else ''}"

        if purpose_stmt:
            exec_summary = (
                f"This document is a {doc_type}{parties_clause}{date_str} spanning {page_str}. "
                f"{purpose_stmt}"
            )
        else:
            doc_article = "an" if doc_type[0].lower() in "aeiou" else "a"
            exec_summary = (
                f"This document is {doc_article} {doc_type}{parties_clause}{date_str} spanning {page_str}. "
                f"It outlines key operational policies and provisions across the agreement."
            )

        from datetime import datetime, timezone
        return DocumentProfileResult(
            document_id=doc.document_id,
            content_hash=doc.content_hash or "hash_unknown",
            document_type=doc_type,
            parties=parties,
            effective_date=effective_date,
            executive_summary=exec_summary,
            major_topics=clean_major_sections,
            source_pages=sorted(list(source_pages)),
            source_sections=clean_major_sections,
            generated_at=datetime.now(timezone.utc).isoformat()
        )

    def format_overview_answer(self, profile: DocumentProfileResult, aspect: Optional[str] = None) -> str:
        """
        Formats structured, grounded answers for document overview queries in a natural, clean, ChatGPT-like style.
        """
        if aspect == "parties":
            if profile.parties:
                party_items = "\n".join(f"* {p}" for p in profile.parties)
                return f"The identified parties to this {profile.document_type} are:\n\n{party_items}"
            return f"The document identifies general parties under a {profile.document_type}, but distinct company names were not explicitly tagged."
        elif aspect == "document_type":
            return f"This document is a **{profile.document_type}**."
        elif aspect == "topics":
            topics_items = "\n".join(f"* {t}" for t in profile.major_topics[:8])
            return f"The major sections and topics covered in this document are:\n\n{topics_items}"
        elif aspect == "concise":
            # Concise, direct executive summary without bullet lists
            return profile.executive_summary.strip()
        elif aspect == "elaborate":
            # Elaborated overview: executive summary + all key attributes and provisions
            lines = [profile.executive_summary]
            bullets = []
            if profile.parties:
                bullets.append(f"* **Parties:** {', '.join(profile.parties)}")
            if profile.effective_date:
                bullets.append(f"* **Effective Date:** {profile.effective_date}")
            if profile.major_topics and profile.major_topics != ["General Provisions"]:
                filtered_topics = [
                    t for t in profile.major_topics
                    if t.lower() != profile.document_type.lower() and t.lower() not in profile.document_type.lower()
                ]
                display_topics = filtered_topics if filtered_topics else profile.major_topics
                if display_topics:
                    bullets.append(f"* **Major Sections & Provisions:** {', '.join(display_topics[:10])}")
            if bullets:
                lines.append("\n" + "\n".join(bullets))
            return "\n".join(lines).strip()
        else:
            lines = [profile.executive_summary]
            bullets = []
            if profile.parties:
                bullets.append(f"* **Parties:** {', '.join(profile.parties)}")
            if profile.effective_date:
                bullets.append(f"* **Effective Date:** {profile.effective_date}")
            if profile.major_topics and profile.major_topics != ["General Provisions"]:
                # Filter out topics that duplicate document title or type
                filtered_topics = [
                    t for t in profile.major_topics
                    if t.lower() != profile.document_type.lower() and t.lower() not in profile.document_type.lower()
                ]
                display_topics = filtered_topics if filtered_topics else profile.major_topics
                if display_topics:
                    bullets.append(f"* **Key Sections:** {', '.join(display_topics[:6])}")

            if bullets:
                lines.append("\n" + "\n".join(bullets))

            return "\n".join(lines).strip()
