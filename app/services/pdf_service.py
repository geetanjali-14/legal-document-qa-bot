import re
from pathlib import Path
from typing import List, Tuple, Optional, Any
import fitz  # PyMuPDF
from app.models.document import PageContent
from app.core.config import settings
from app.core.logging import logger
from app.core.errors import PageLimitExceededError


class PDFExtractionError(Exception):
    """Raised when PDF extraction fails or is invalid."""
    pass


class ScannedPDFError(PDFExtractionError):
    """Raised when PDF appears to be scanned with no extractable text."""
    pass


class PDFService:
    def __init__(self, min_char_threshold_per_page: int = 20, max_pages: Optional[int] = None):
        self.min_char_threshold_per_page = min_char_threshold_per_page
        self.max_pages = max_pages

    def clean_text(self, text: str) -> str:
        """Normalize whitespace, clean ligatures, and remove control characters."""
        if not text:
            return ""
        # Replace non-breaking spaces and tabs
        text = text.replace("\xa0", " ").replace("\t", " ")
        # Fix hyphens across line breaks (e.g., "termi-\nnation" -> "termination")
        text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
        # Normalize excessive newlines and spaces
        text = re.sub(r'[ \t\r\f\v]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        return text.strip()

    def extract_text_and_pages(self, pdf_path: Path) -> List[PageContent]:
        """
        Extract text from PDF while preserving page numbers.
        Detects empty or scanned PDFs safely.
        """
        if not pdf_path.exists():
            raise PDFExtractionError(f"File not found: {pdf_path}")

        try:
            doc = fitz.open(str(pdf_path))
        except Exception as e:
            logger.error(f"Failed to open PDF {pdf_path.name}: {str(e)}")
            raise PDFExtractionError(f"Corrupted or invalid PDF file: {str(e)}")

        try:
            if doc.page_count == 0:
                raise PDFExtractionError("PDF contains zero pages.")

            page_limit = self.max_pages if self.max_pages is not None else settings.MAX_DOCUMENT_PAGES
            if doc.page_count > page_limit:
                raise PageLimitExceededError(
                    f"Document page count ({doc.page_count}) exceeds maximum allowed limit of {page_limit} pages."
                )

            pages_content: List[PageContent] = []
            total_chars = 0

            # Layout-aware extraction preserving legal clause and block boundaries
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                blocks = page.get_text("blocks")
                cleaned_blocks = []
                for b in blocks:
                    lines = [l.strip() for l in b[4].split("\n") if l.strip()]
                    if not lines:
                        continue
                    formatted_lines = []
                    for line in lines:
                        if not formatted_lines:
                            formatted_lines.append(line)
                        elif re.match(r'^(?:(?:Section|SECTION|Article|ARTICLE|Clause|CLAUSE|\d+(?:\.\d+)*)\.?(?:\s+[A-Z]|$)|[A-Z\s]{4,40}:?$)', line):
                            formatted_lines.append(line)
                        else:
                            formatted_lines[-1] += " " + line
                    cleaned_blocks.append("\n".join(formatted_lines))

                raw_text = "\n\n".join(cleaned_blocks) if cleaned_blocks else page.get_text("text")
                cleaned = self.clean_text(raw_text)

                # Selective OCR hook for image-based/low-text pages
                if len(cleaned) < self.min_char_threshold_per_page:
                    cleaned_ocr = self._attempt_selective_ocr(page, page_index + 1)
                    if cleaned_ocr:
                        cleaned = cleaned_ocr

                char_count = len(cleaned)
                total_chars += char_count

                pages_content.append(
                    PageContent(
                        page_number=page_index + 1,
                        text=cleaned,
                        char_count=char_count
                    )
                )

            # If document appears scanned or has virtually no text, attempt Docling
            if total_chars < (self.min_char_threshold_per_page * len(pages_content)):
                try:
                    from docling.document_converter import DocumentConverter
                    converter = DocumentConverter()
                    res = converter.convert(str(pdf_path))
                    d_doc = res.document
                    docling_pages: dict = {}
                    for item, _ in d_doc.iterate_items():
                        text = getattr(item, "text", "")
                        if not text or not text.strip():
                            continue
                        prov = getattr(item, "prov", None)
                        p_no = prov[0].page_no if (prov and len(prov) > 0) else 1
                        docling_pages.setdefault(p_no, []).append(text.strip())

                    if docling_pages:
                        pages_content = []
                        total_chars = 0
                        for p_num in range(1, doc.page_count + 1):
                            p_items = docling_pages.get(p_num, [])
                            page_text = self.clean_text("\n\n".join(p_items))
                            c_count = len(page_text)
                            total_chars += c_count
                            pages_content.append(
                                PageContent(
                                    page_number=p_num,
                                    text=page_text,
                                    char_count=c_count
                                )
                            )
                except Exception as d_err:
                    logger.debug(f"Docling fallback skipped or failed for {pdf_path.name}: {d_err}")

            if total_chars < (self.min_char_threshold_per_page * len(pages_content)):
                raise ScannedPDFError(
                    "This document appears to be scanned or image-based and does not contain extractable text. "
                    "OCR support is required to process this document."
                )

            logger.info(f"Extracted {len(pages_content)} pages ({total_chars} chars) from {pdf_path.name}")
            return pages_content

        finally:
            doc.close()

    def _attempt_selective_ocr(self, page: Any, page_num: int) -> Optional[str]:
        """Attempt OCR on a single low-text page using RapidOCR or pytesseract if available."""
        try:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            np_img = np.array(img)
            engine = RapidOCR()
            result, _ = engine(np_img)
            if result:
                lines = [str(line_data[1]).strip() for line_data in result if line_data and len(line_data) >= 2 and line_data[1]]
                cleaned = self.clean_text("\n".join(lines))
                if cleaned:
                    logger.info(f"[Selective OCR] Successfully extracted {len(cleaned)} chars on page {page_num} via RapidOCR")
                    return cleaned
        except Exception as ocr_err:
            logger.debug(f"[Selective OCR] RapidOCR failed for page {page_num}: {ocr_err}")

        try:
            import pytesseract
            from PIL import Image
            import io

            pix = page.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_text = pytesseract.image_to_string(img)
            cleaned = self.clean_text(ocr_text)
            if cleaned:
                logger.info(f"[Selective OCR] Successfully extracted {len(cleaned)} chars on page {page_num} via pytesseract")
                return cleaned
        except Exception as ocr_err:
            logger.debug(f"[Selective OCR] pytesseract unavailable for page {page_num}: {ocr_err}")
        return None
