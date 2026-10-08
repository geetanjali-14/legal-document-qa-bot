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

    def detect_section_header(self, text: str) -> Optional[str]:
        """Attempt to extract legal section heading from a line or block."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        for line in lines[:3]:  # Check first few lines
            if self.heading_pattern.fullmatch(line):
                return line
            inline_heading = self.inline_numbered_heading_pattern.match(line)
            if inline_heading:
                return inline_heading.group(1).rstrip()
        return None

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
        """
        chunks: List[DocumentChunk] = []
        current_section = "General / Preamble"

        for page in pages:
            page_text = page.text
            if not page_text or len(page_text.strip()) == 0:
                continue

            # Split into natural paragraphs first
            paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]

            buffer = ""
            chunk_section = current_section
            for paragraph in paragraphs:
                # Check if paragraph begins with a section heading
                detected_section = self.detect_section_header(paragraph)
                if detected_section:
                    current_section = detected_section
                    if not buffer:
                        chunk_section = current_section

                # Check if adding this paragraph exceeds chunk_size
                if len(buffer) + len(paragraph) + 1 > self.chunk_size and len(buffer) >= self.min_chunk_size:
                    # Flush current buffer
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
                        overlap_text = buffer[overlap_start:]
                        buffer = overlap_text + " " + paragraph
                    else:
                        buffer = paragraph
                    chunk_section = current_section
                else:
                    if buffer:
                        buffer += "\n\n" + paragraph
                    else:
                        buffer = paragraph
                        chunk_section = current_section

            # Flush any remaining buffer for the page
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
                # If leftover text is small, append to previous chunk to not lose context
                chunks[-1].text += "\n\n" + buffer.strip()
                chunks[-1].token_count = len(chunks[-1].text.split())
                chunks[-1].content_hash = hashlib.sha256(chunks[-1].text.encode("utf-8")).hexdigest()

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
