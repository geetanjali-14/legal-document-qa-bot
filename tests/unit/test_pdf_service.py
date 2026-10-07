import pytest
from pathlib import Path
import fitz
from app.services.pdf_service import PDFService, ScannedPDFError, PDFExtractionError
from app.models.document import PageContent


def test_pdf_clean_text():
    service = PDFService()
    raw = "The   agreement\xa0is  hereby\ntermi-\nnated\n\n\nwith  notice."
    cleaned = service.clean_text(raw)
    assert "terminated" in cleaned
    assert "\xa0" not in cleaned
    assert "  " not in cleaned


def test_extract_valid_pdf(tmp_path: Path):
    pdf_path = tmp_path / "valid.pdf"
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "This is page one of our valid legal agreement.")
    p2 = doc.new_page()
    p2.insert_text((50, 50), "This is page two containing Section 2 Termination clauses.")
    doc.save(str(pdf_path))
    doc.close()

    service = PDFService()
    pages = service.extract_text_and_pages(pdf_path)

    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert "page one" in pages[0].text
    assert pages[1].page_number == 2
    assert "Termination" in pages[1].text


def test_detect_scanned_pdf(tmp_path: Path):
    # Blank PDF with no text represents scanned PDF without OCR
    pdf_path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    service = PDFService(min_char_threshold_per_page=20)
    with pytest.raises(ScannedPDFError) as exc_info:
        service.extract_text_and_pages(pdf_path)

    assert "OCR support is required" in str(exc_info.value)


def test_missing_pdf():
    service = PDFService()
    with pytest.raises(PDFExtractionError):
        service.extract_text_and_pages(Path("non_existent_file.pdf"))
