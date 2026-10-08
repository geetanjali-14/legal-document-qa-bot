import io
import re
from pathlib import Path
from typing import List, Optional
import numpy as np
from PIL import Image

from app.models.document import PageContent
from app.core.config import settings
from app.core.logging import logger
from app.core.errors import PageLimitExceededError


class ImageExtractionError(Exception):
    """Raised when image processing or OCR fails."""
    pass


class OCRNoTextError(ImageExtractionError):
    """Raised when OCR extracts no meaningful text from an image document."""
    pass


class ImageService:
    def __init__(self, min_char_threshold_per_page: int = 15, max_pages: Optional[int] = None):
        self.min_char_threshold_per_page = min_char_threshold_per_page
        self.max_pages = max_pages
        self._ocr_engine = None

    def _get_ocr_engine(self):
        if self._ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr_engine = RapidOCR()
        return self._ocr_engine

    def clean_text(self, text: str) -> str:
        """Normalize whitespace, clean OCR artifacts, and normalize line breaks."""
        if not text:
            return ""
        text = text.replace("\xa0", " ").replace("\t", " ")
        # Fix hyphens across line breaks
        text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
        # Normalize multiple spaces
        text = re.sub(r'[ \t\r\f\v]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        return text.strip()

    def extract_text_and_pages(self, image_path: Path) -> List[PageContent]:
        """
        Extract text from an image file (single image or multi-frame TIFF)
        using OCR while preserving page/frame numbers and metadata.
        """
        if not image_path.exists():
            raise ImageExtractionError(f"File not found: {image_path}")

        try:
            with Image.open(image_path) as img:
                n_frames = getattr(img, "n_frames", 1)
                page_limit = self.max_pages if self.max_pages is not None else settings.MAX_DOCUMENT_PAGES
                if n_frames > page_limit:
                    raise PageLimitExceededError(
                        f"Document page count ({n_frames}) exceeds maximum allowed limit of {page_limit} pages."
                    )

                engine = self._get_ocr_engine()
                pages_content: List[PageContent] = []
                total_chars = 0

                for frame_idx in range(n_frames):
                    img.seek(frame_idx)
                    frame_rgb = img.convert("RGB")
                    np_img = np.array(frame_rgb)

                    result, _ = engine(np_img)
                    frame_lines = []
                    if result:
                        for line_data in result:
                            # line_data format: [coords, text, confidence]
                            if line_data and len(line_data) >= 2 and line_data[1]:
                                frame_lines.append(str(line_data[1]).strip())

                    raw_text = "\n".join(frame_lines)
                    cleaned = self.clean_text(raw_text)
                    char_count = len(cleaned)
                    total_chars += char_count

                    pages_content.append(
                        PageContent(
                            page_number=frame_idx + 1,
                            text=cleaned,
                            char_count=char_count
                        )
                    )

            if total_chars < self.min_char_threshold_per_page:
                raise OCRNoTextError(
                    "OCR could not extract meaningful text from this image document. "
                    "Ensure the document is legible and not blank."
                )

            logger.info(f"Extracted {len(pages_content)} pages ({total_chars} chars) via OCR from {image_path.name}")
            return pages_content

        except (ImageExtractionError, PageLimitExceededError):
            raise
        except Exception as e:
            logger.error(f"Failed to process image {image_path.name}: {str(e)}")
            raise ImageExtractionError(f"Corrupted or invalid image file: {str(e)}")

