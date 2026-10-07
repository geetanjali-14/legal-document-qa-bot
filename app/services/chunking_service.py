import re
import uuid
from typing import List, Optional, Tuple
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
            r'^(?:(?:Section|Article|Clause)\s+[0-9IVXLCDM]+(?:\.[0-9]+)*'
            r'|(?:\d+\.(?:\d+\.)*)\s+[A-Z][a-zA-Z0-9\s,\'-]{2,60}'
            r'|[A-Z\s]{4,40}:?$)',
            re.MULTILINE
        )

    def detect_section_header(self, text: str) -> Optional[str]:
        """Attempt to extract legal section heading from a line or block."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        for line in lines[:3]:  # Check first few lines
            if self.heading_pattern.match(line):
                return line
        return None

    def chunk_document(
        self,
        document_id: str,
        document_name: str,
        pages: List[PageContent]
    ) -> List[DocumentChunk]:
        """
        Split document pages into semantically cohesive legal chunks while strictly
        preserving page numbers and section hierarchy.
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
                    chunks.append(
                        DocumentChunk(
                            chunk_id=chunk_id,
                            document_id=document_id,
                            document_name=document_name,
                            page_number=page.page_number,
                            section=chunk_section,
                            text=buffer.strip(),
                            token_count=len(buffer.split())
                        )
                    )
                    # Prepare next buffer with overlap if applicable
                    if self.chunk_overlap > 0 and len(buffer) > self.chunk_overlap:
                        overlap_text = buffer[-self.chunk_overlap:]
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
                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        document_name=document_name,
                        page_number=page.page_number,
                        section=chunk_section,
                        text=buffer.strip(),
                        token_count=len(buffer.split())
                    )
                )
            elif buffer.strip() and chunks:
                # If leftover text is small, append to previous chunk to not lose context
                chunks[-1].text += "\n\n" + buffer.strip()
                chunks[-1].token_count = len(chunks[-1].text.split())

        logger.info(f"Generated {len(chunks)} chunks for document {document_name} ({document_id})")
        return chunks
