import re
import uuid
import hashlib
from typing import List, Optional, Tuple, Any
from app.models.document import DocumentChunk, PageContent
from app.core.logging import logger


class ChunkingService:
    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

        # Regex patterns common in legal agreements (e.g., "Section 1.", "Article IV", "1.2 Termination", etc.)
        self.heading_pattern = re.compile(
            r'(?:'
            r'(?:Section|Article|Clause)\s+[0-9IVXLCDM]+(?:\.[0-9]+)*(?:[.:)]\s+[A-Z][A-Za-z0-9\s,&\'()/:-]{2,100})?'
            r'|\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9\s,:&\'()/:-]{2,100}'
            r'|[A-Z][A-Z\s]{3,40}:?'
            r')'
        )
        self.inline_numbered_heading_pattern = re.compile(
            r"^(\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z\s,&'()/:-]{2,60}?)"
            r"(?=\s+\d+(?:\.\d+)*\.?\s+[A-Z])"
        )
        self.concise_heading_pattern = re.compile(
            r"^([A-Z][A-Za-z\s,&'()/:-]{2,60}?)(?:\s+\d+(?:\.\d+)*\b|\s*:\s*)"
        )

    def detect_section_header(self, text: str) -> Optional[str]:
        """Attempt to extract legal section heading from a line or block."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        stopwords = {'of', 'and', 'the', 'in', 'on', 'for', 'to', 'a', 'an', 'as', 'by', 'with'}
        for line in lines[:3]:  # Check first few lines
            if self.heading_pattern.fullmatch(line):
                return line
            inline_heading = self.inline_numbered_heading_pattern.match(line)
            if inline_heading:
                return inline_heading.group(1).rstrip()
            concise_match = self.concise_heading_pattern.match(line)
            if concise_match:
                cand = concise_match.group(1).strip()
                words = cand.split()
                if 1 <= len(words) <= 7 and all(w[0].isupper() or w.lower() in stopwords for w in words if w):
                    return cand
            # Check title-cased heading without period
            if len(line) <= 60 and not line.endswith('.'):
                words = line.split()
                if 1 <= len(words) <= 7 and all(w[0].isupper() or w.lower() in stopwords for w in words if w):
                    return line
        return None

    def _parse_legal_units(self, pages: List[PageContent]) -> List[dict]:
        """
        Decomposes document pages into legal structural units:
        - Major headings (RENTAL AGREEMENT, DEED, etc.)
        - Individual numbered clauses (Clause 1 to 21, etc.)
        - Annexures / Schedules / Exhibits (ANNEXURE-I, etc.)
        - Execution and witness blocks
        - Subclauses and general paragraphs
        """
        clause_pat = re.compile(
            r"^(?:(?:Clause|CLAUSE|Section|SECTION|Article|ARTICLE)\s+([0-9IVXLCDM]+(?:\.[0-9]+)*)|(\d+)\.)\s*(.*)$",
            re.IGNORECASE
        )
        annexure_pat = re.compile(
            r"^(ANNEXURE[- ]?[IVXLCDM\d]+|SCHEDULE[- ]?[IVXLCDM\d]+|EXHIBIT[- ]?[IVXLCDM\d]+)\b.*$",
            re.IGNORECASE
        )
        major_heading_pat = re.compile(
            r"^(RENTAL AGREEMENT|NOW THIS DEED WITNESSETH AS FOLLOWS:?|IN WITNESS WHEREOF.*|WITNESSES:?|OWNER|TENANT)$",
            re.IGNORECASE
        )

        units: List[dict] = []
        current_unit: Optional[dict] = None
        in_witnesses = False

        for page in pages:
            page_text = page.text
            if not page_text or not page_text.strip():
                continue

            # Split by double newline or natural paragraph breaks
            paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]
            for para in paragraphs:
                lines = [l.strip() for l in para.split("\n") if l.strip()]
                first_line = lines[0] if lines else ""

                if re.match(r"^WITNESSES:?$", first_line, re.IGNORECASE):
                    in_witnesses = True
                    if current_unit:
                        units.append(current_unit)
                    current_unit = {
                        "sec_title": "Execution and Witnesses",
                        "sec_num": "Execution",
                        "clause_num": None,
                        "page_number": page.page_number,
                        "text": para
                    }
                    continue

                if in_witnesses:
                    if current_unit:
                        current_unit["text"] += "\n\n" + para
                    continue

                is_new = False
                sec_title = None
                sec_num = None
                clause_num = None

                m_annex = annexure_pat.match(first_line)
                m_major = major_heading_pat.match(first_line)
                m_clause = clause_pat.match(first_line)
                detected_hdr = self.detect_section_header(first_line)

                if m_annex:
                    is_new = True
                    sec_title = m_annex.group(1).upper()
                    sec_num = sec_title
                    clause_num = None
                elif m_clause:
                    is_new = True
                    c_num = m_clause.group(1) or m_clause.group(2)
                    rest_title = m_clause.group(3).strip() if m_clause.group(3) else ""
                    sec_num = f"Clause {c_num}"
                    clause_num = c_num
                    # Check if the text following the clause number is a concise heading (e.g. "Term of Agreement", "Termination")
                    words = rest_title.split()
                    stopwords = {'of', 'and', 'the', 'in', 'on', 'for', 'to', 'a', 'an', 'as', 'by', 'with'}
                    if 1 <= len(words) <= 7 and not rest_title.endswith('.') and all(w[0].isupper() or w.lower() in stopwords for w in words if w):
                        sec_title = rest_title
                    else:
                        sec_title = f"Clause {c_num}"
                elif m_major:
                    is_new = True
                    sec_title = first_line
                    sec_num = None
                    clause_num = None
                elif detected_hdr:
                    is_new = True
                    sec_num, sec_title, clause_num = self._extract_hierarchy_parts(detected_hdr, para)

                if is_new:
                    if current_unit:
                        units.append(current_unit)
                    current_unit = {
                        "sec_title": sec_title or "General",
                        "sec_num": sec_num,
                        "clause_num": clause_num,
                        "page_number": page.page_number,
                        "text": para
                    }
                else:
                    if current_unit:
                        # If current unit is getting very large, flush it to prevent monster chunks
                        if len(current_unit["text"]) + len(para) > (self.chunk_size * 2):
                            units.append(current_unit)
                            current_unit = {
                                "sec_title": current_unit["sec_title"],
                                "sec_num": current_unit["sec_num"],
                                "clause_num": current_unit["clause_num"],
                                "page_number": page.page_number,
                                "text": para
                            }
                        else:
                            current_unit["text"] += "\n\n" + para
                    else:
                        current_unit = {
                            "sec_title": "General / Preamble",
                            "sec_num": None,
                            "clause_num": None,
                            "page_number": page.page_number,
                            "text": para
                        }

        if current_unit:
            units.append(current_unit)
        return units

    def chunk_document(
        self,
        document_id: str,
        document_name: str,
        pages: List[PageContent],
        structure: Optional[Any] = None
    ) -> List[DocumentChunk]:
        """
        Split document pages into semantically cohesive legal chunks while strictly
        preserving page numbers, section hierarchy, and structural breadcrumbs.
        Identifies clauses, annexures, and execution blocks as discrete retrieval units.
        """
        chunks: List[DocumentChunk] = []

        # 1. Parse into cohesive legal units
        legal_units = self._parse_legal_units(pages)

        # Fallback to standard windowing if no structured units detected
        if not legal_units or len(legal_units) <= 1:
            current_section = "General / Preamble"
            for page in pages:
                page_text = page.text
                if not page_text or len(page_text.strip()) == 0:
                    continue
                paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]
                buffer = ""
                chunk_section = current_section
                for paragraph in paragraphs:
                    detected_section = self.detect_section_header(paragraph)
                    if detected_section:
                        current_section = detected_section
                        if not buffer:
                            chunk_section = current_section
                    if len(buffer) + len(paragraph) + 1 > self.chunk_size and len(buffer) >= self.min_chunk_size:
                        chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
                        breadcrumbs = self._resolve_breadcrumbs(chunk_section, structure)
                        sec_num, sec_title, clause_num = self._extract_hierarchy_parts(chunk_section, buffer)
                        c_hash = hashlib.sha256(buffer.strip().encode("utf-8")).hexdigest()
                        parent_id = f"sec_{re.sub(r'[^a-zA-Z0-9]', '', sec_num)}" if sec_num else None
                        chunks.append(
                            DocumentChunk(
                                chunk_id=chunk_id,
                                document_id=document_id,
                                document_name=document_name,
                                page_number=page.page_number,
                                section=chunk_section,
                                section_number=sec_num,
                                section_title=sec_title,
                                clause_number=clause_num,
                                parent_chunk_id=parent_id,
                                content_hash=c_hash,
                                breadcrumbs=breadcrumbs,
                                text=buffer.strip(),
                                token_count=len(buffer.split())
                            )
                        )
                        # Prepare next buffer with overlap if applicable
                        if self.chunk_overlap > 0 and len(buffer) > self.chunk_overlap:
                            overlap_start = len(buffer) - self.chunk_overlap
                            while (
                                overlap_start > 0
                                and buffer[overlap_start - 1].isalnum()
                                and buffer[overlap_start].isalnum()
                            ):
                                overlap_start -= 1
                            overlap_text = buffer[overlap_start:].strip()
                            buffer = (overlap_text + " " + paragraph) if overlap_text else paragraph
                        else:
                            buffer = paragraph
                        chunk_section = current_section
                    else:
                        buffer = (buffer + "\n\n" + paragraph) if buffer else paragraph
                if buffer.strip() and len(buffer.strip()) >= self.min_chunk_size:
                    chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
                    breadcrumbs = self._resolve_breadcrumbs(chunk_section, structure)
                    sec_num, sec_title, clause_num = self._extract_hierarchy_parts(chunk_section, buffer)
                    c_hash = hashlib.sha256(buffer.strip().encode("utf-8")).hexdigest()
                    parent_id = f"sec_{re.sub(r'[^a-zA-Z0-9]', '', sec_num)}" if sec_num else None
                    chunks.append(
                        DocumentChunk(
                            chunk_id=chunk_id,
                            document_id=document_id,
                            document_name=document_name,
                            page_number=page.page_number,
                            section=chunk_section,
                            section_number=sec_num,
                            section_title=sec_title,
                            clause_number=clause_num,
                            parent_chunk_id=parent_id,
                            content_hash=c_hash,
                            breadcrumbs=breadcrumbs,
                            text=buffer.strip(),
                            token_count=len(buffer.split())
                        )
                    )
                elif buffer.strip() and chunks:
                    chunks[-1].text += "\n\n" + buffer.strip()
                    chunks[-1].token_count = len(chunks[-1].text.split())
                    chunks[-1].content_hash = hashlib.sha256(chunks[-1].text.encode("utf-8")).hexdigest()
        else:
            for unit in legal_units:
                unit_text = unit["text"].strip()
                if not unit_text:
                    continue

                sec_title = unit.get("sec_title") or "General"
                sec_num = unit.get("sec_num")
                clause_num = unit.get("clause_num")
                page_no = unit.get("page_number") or 1
                breadcrumbs = self._resolve_breadcrumbs(sec_title, structure)
                parent_id = f"sec_{re.sub(r'[^a-zA-Z0-9]', '', sec_num)}" if sec_num else None

                # If legal unit text fits within reasonable size, keep it intact
                # otherwise split across paragraph boundaries while preserving section metadata
                if len(unit_text) <= max(self.chunk_size * 2, 800):
                    chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
                    c_hash = hashlib.sha256(unit_text.encode("utf-8")).hexdigest()
                    chunks.append(
                        DocumentChunk(
                            chunk_id=chunk_id,
                            document_id=document_id,
                            document_name=document_name,
                            page_number=page_no,
                            section=sec_title,
                            section_number=sec_num,
                            section_title=sec_title,
                            clause_number=clause_num,
                            parent_chunk_id=parent_id,
                            content_hash=c_hash,
                            breadcrumbs=breadcrumbs,
                            text=unit_text,
                            token_count=len(unit_text.split())
                        )
                    )
                else:
                    # Split unit paragraphs safely
                    unit_paras = [p.strip() for p in unit_text.split("\n\n") if p.strip()]
                    buffer = ""
                    for p_item in unit_paras:
                        if len(buffer) + len(p_item) + 1 > self.chunk_size and len(buffer) >= self.min_chunk_size:
                            chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
                            c_hash = hashlib.sha256(buffer.strip().encode("utf-8")).hexdigest()
                            chunks.append(
                                DocumentChunk(
                                    chunk_id=chunk_id,
                                    document_id=document_id,
                                    document_name=document_name,
                                    page_number=page_no,
                                    section=sec_title,
                                    section_number=sec_num,
                                    section_title=sec_title,
                                    clause_number=clause_num,
                                    parent_chunk_id=parent_id,
                                    content_hash=c_hash,
                                    breadcrumbs=breadcrumbs,
                                    text=buffer.strip(),
                                    token_count=len(buffer.split())
                                )
                            )
                            buffer = p_item
                        else:
                            buffer = (buffer + "\n\n" + p_item) if buffer else p_item

                    if buffer.strip():
                        chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
                        c_hash = hashlib.sha256(buffer.strip().encode("utf-8")).hexdigest()
                        chunks.append(
                            DocumentChunk(
                                chunk_id=chunk_id,
                                document_id=document_id,
                                document_name=document_name,
                                page_number=page_no,
                                section=sec_title,
                                section_number=sec_num,
                                section_title=sec_title,
                                clause_number=clause_num,
                                parent_chunk_id=parent_id,
                                content_hash=c_hash,
                                breadcrumbs=breadcrumbs,
                                text=buffer.strip(),
                                token_count=len(buffer.split())
                            )
                        )

        # Assign paragraph numbers across chunks in document
        for idx, chk in enumerate(chunks, 1):
            chk.paragraph_number = idx

        logger.info(f"Generated {len(chunks)} chunks for document {document_name} ({document_id})")
        return chunks

    def _extract_hierarchy_parts(self, section: str, text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract section number, section title, and clause number from section header or text."""
        sec_num = None
        sec_title = section
        clause_num = None

        # Check section number (e.g., Section 15 or 15.2 or Article 3)
        m_sec = re.search(r'(?:Section|Article|Clause)\s+([0-9IVXLCDM]+(?:\.[0-9]+)*)', section, re.I)
        if m_sec:
            sec_num = m_sec.group(1)
        else:
            m_num = re.match(r'^(\d+(?:\.\d+)*)\.?', section)
            if m_num:
                sec_num = m_num.group(1)

        # Check clause number in text e.g., 15.3 or (a) or (b)
        m_clause = re.search(r'\b(\d+\.\d+(?:\.\d+)*|\([a-z0-9]+\))\b', text[:120])
        if m_clause:
            clause_num = m_clause.group(1)

        return sec_num, sec_title, clause_num

    def _resolve_breadcrumbs(self, section: str, structure: Optional[Any]) -> List[str]:
        """Look up breadcrumbs from structure tree if available, or generate default breadcrumbs."""
        if structure and hasattr(structure, "flat_sections"):
            # Check normalized key
            clean_key = re.sub(r'[^a-z0-9]', '', section.lower())
            node = structure.flat_sections.get(clean_key)
            if not node:
                for k, v in structure.flat_sections.items():
                    if k in clean_key or clean_key in k:
                        node = v
                        break
            if node and node.breadcrumb:
                return list(node.breadcrumb)
        return [section] if section else ["General"]
