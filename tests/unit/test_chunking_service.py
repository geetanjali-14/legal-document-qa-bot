from app.services.chunking_service import ChunkingService
from app.models.document import PageContent


def test_chunking_preserves_page_and_section():
    service = ChunkingService(chunk_size=150, chunk_overlap=30, min_chunk_size=20)
    pages = [
        PageContent(
            page_number=1,
            text="Section 1. Definitions\n\nThis agreement defines terms.\n\nSection 2. Termination\n\nEither party may terminate with 30 days notice.",
            char_count=130
        ),
        PageContent(
            page_number=2,
            text="Section 3. Governing Law\n\nThis contract is governed by Delaware law.",
            char_count=70
        )
    ]

    chunks = service.chunk_document("doc_1", "contract.pdf", pages)
    assert len(chunks) >= 2

    # Verify every chunk retains document_id, page_number, and detected section
    for chunk in chunks:
        assert chunk.document_id == "doc_1"
        assert chunk.page_number in [1, 2]
        assert chunk.section is not None
        assert len(chunk.text) > 0


def test_chunking_small_text_fallback():
    service = ChunkingService(chunk_size=300, chunk_overlap=50, min_chunk_size=10)
    pages = [
        PageContent(page_number=1, text="Brief short clause.", char_count=19)
    ]
    chunks = service.chunk_document("doc_2", "short.pdf", pages)
    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert "Brief short clause" in chunks[0].text
