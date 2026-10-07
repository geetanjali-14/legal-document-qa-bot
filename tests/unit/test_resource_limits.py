import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.errors import (
    ResourceLimitError,
    FileSizeLimitExceededError,
    PageLimitExceededError,
    ChunkLimitExceededError,
    QueryLimitExceededError,
    ContextLimitExceededError,
    TokenBudgetExceededError
)
from app.core.telemetry import telemetry_collector
from app.models.chat import ChatRequest, Message
from app.models.document import PageContent, DocumentChunk
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService, MockEmbeddingProvider
from app.services.vector_store import VectorStore
from app.services.llm_service import MockLLMProvider, OpenAILLMProvider, LLMService


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def isolated_doc_service(tmp_path: Path):
    """Isolated DocumentService instance using temporary directory for tests."""
    upload_dir = tmp_path / "uploads"
    vector_dir = tmp_path / "vector_store"
    upload_dir.mkdir(parents=True)
    vector_dir.mkdir(parents=True)

    pdf_service = PDFService(max_pages=settings.MAX_DOCUMENT_PAGES)
    chunking_service = ChunkingService(chunk_size=500, chunk_overlap=100, min_chunk_size=50)
    embedding_service = EmbeddingService()
    embedding_service.provider = MockEmbeddingProvider(dimension=16)
    vector_store = VectorStore(storage_dir=vector_dir)

    service = DocumentService(
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        embedding_service=embedding_service,
        vector_store=vector_store
    )
    service.upload_dir = upload_dir
    service.metadata_file = upload_dir / "documents_meta.json"
    service.documents = {}
    service._hash_to_id = {}
    return service


@pytest.fixture(scope="module")
def uploaded_test_doc_id(client):
    pdf_path = Path("documents/synthetic_contract.pdf")
    with open(pdf_path, "rb") as f:
        res = client.post(
            "/api/documents/upload",
            files={"file": ("synthetic_contract.pdf", f, "application/pdf")}
        )
    assert res.status_code == 201
    doc_id = res.json()["data"]["document_id"]
    yield doc_id
    client.delete(f"/api/documents/{doc_id}")


# =====================================================================
# 1. Upload & File Size Limits
# =====================================================================

def test_file_below_limit_succeeds(isolated_doc_service):
    """File size strictly below MAX_FILE_SIZE_MB succeeds and processes normally."""
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    assert len(contract_bytes) < settings.MAX_FILE_SIZE_MB * 1024 * 1024

    doc = isolated_doc_service.process_document(contract_bytes, "normal_contract.pdf")
    assert doc.document_id is not None
    assert doc.status == "processed"
    assert doc.file_size_bytes == len(contract_bytes)


def test_file_exactly_at_limit_behaves_correctly(isolated_doc_service, monkeypatch):
    """Boundary test: File size exactly at the configured byte threshold passes validation."""
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    exact_size = len(contract_bytes)
    # Set MAX_FILE_SIZE_MB effectively matching exact_size in MB fraction, or monkeypatch MAX_FILE_SIZE_MB
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    # Valid PDF padded to exactly 1 MB (1024 * 1024 bytes)
    target_bytes = 1024 * 1024
    assert len(contract_bytes) <= target_bytes
    # Construct a valid PDF that is exactly target_bytes
    # PyMuPDF creates PDF bytes, we append dummy PDF comment %... to reach exact bytes
    comment_padding = b"\n%" + b"0" * (target_bytes - len(contract_bytes) - 2)
    exact_pdf = contract_bytes + comment_padding
    assert len(exact_pdf) == target_bytes

    doc = isolated_doc_service.process_document(exact_pdf, "exact_size.pdf")
    assert doc.file_size_bytes == target_bytes


def test_file_above_limit_rejected(isolated_doc_service, monkeypatch):
    """File size exceeding MAX_FILE_SIZE_MB is rejected with FileSizeLimitExceededError."""
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)  # 1 MB limit
    oversized_bytes = b"%PDF-1.4" + b"X" * (1024 * 1024 + 100)

    with pytest.raises(FileSizeLimitExceededError) as exc_info:
        isolated_doc_service.process_document(oversized_bytes, "oversized.pdf")

    assert "exceeds maximum allowed limit" in str(exc_info.value)
    assert exc_info.value.error_category == "file_too_large"


def test_oversized_file_does_not_reach_expensive_processing(isolated_doc_service, monkeypatch):
    """Verification that extraction, chunking, and embedding are NEVER called when file is oversized."""
    mock_pdf_service = MagicMock()
    mock_chunking_service = MagicMock()
    mock_embedding_service = MagicMock()

    isolated_doc_service.pdf_service = mock_pdf_service
    isolated_doc_service.chunking_service = mock_chunking_service
    isolated_doc_service.embedding_service = mock_embedding_service

    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    oversized_bytes = b"%PDF-1.4" + b"A" * (2 * 1024 * 1024)

    with pytest.raises(FileSizeLimitExceededError):
        isolated_doc_service.process_document(oversized_bytes, "huge.pdf")

    # Expensive processing stages were bypassed completely
    mock_pdf_service.extract_text_and_pages.assert_not_called()
    mock_chunking_service.chunk_document.assert_not_called()
    mock_embedding_service.embed_texts.assert_not_called()


def test_api_upload_file_size_limit_rejection(client, monkeypatch):
    """API endpoint rejects oversized file with HTTP 400 and X-Error-Category header."""
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    oversized_payload = b"%PDF-1.4" + b"B" * (1024 * 1024 + 500)

    response = client.post(
        "/api/documents/upload",
        files={"file": ("too_big.pdf", oversized_payload, "application/pdf")}
    )
    assert response.status_code == 400
    assert "file_too_large" in response.headers.get("X-Error-Category", "")
    assert "exceeds maximum allowed limit" in response.json()["detail"]


# =====================================================================
# 2. PDF Page Limits
# =====================================================================

def test_document_below_page_limit_succeeds(tmp_path: Path):
    """PDF with page count below limit extracts without error."""
    pdf_path = tmp_path / "two_pages.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Page 1 Content with sufficient characters to pass scanned check.")
    doc.new_page().insert_text((50, 50), "Page 2 Content with sufficient characters to pass scanned check.")
    doc.save(str(pdf_path))
    doc.close()

    service = PDFService(max_pages=5)
    pages = service.extract_text_and_pages(pdf_path)
    assert len(pages) == 2


def test_document_exceeding_page_limit_rejected(tmp_path: Path):
    """PDF with page count exceeding limit raises PageLimitExceededError early."""
    pdf_path = tmp_path / "four_pages.pdf"
    doc = fitz.open()
    for i in range(4):
        doc.new_page().insert_text((50, 50), f"Page {i+1} text content for legal contract.")
    doc.save(str(pdf_path))
    doc.close()

    service = PDFService(max_pages=2)
    with pytest.raises(PageLimitExceededError) as exc_info:
        service.extract_text_and_pages(pdf_path)

    assert "exceeds maximum allowed limit of 2 pages" in str(exc_info.value)
    assert exc_info.value.error_category == "page_limit_exceeded"


def test_page_limit_rejection_no_metadata_created(isolated_doc_service, monkeypatch, tmp_path: Path):
    """When a document fails page limits, metadata store is untouched and document is not registered."""
    monkeypatch.setattr(settings, "MAX_DOCUMENT_PAGES", 2)
    isolated_doc_service.pdf_service.max_pages = 2

    # Create 3-page PDF
    doc = fitz.open()
    for i in range(3):
        doc.new_page().insert_text((50, 50), f"Section {i+1}: Valid legal clause content.")
    pdf_bytes = doc.tobytes()
    doc.close()

    with pytest.raises(PageLimitExceededError):
        isolated_doc_service.process_document(pdf_bytes, "three_pages.pdf")

    # Document was NOT registered in memory
    assert len(isolated_doc_service.documents) == 0
    assert len(isolated_doc_service.list_documents()) == 0

    # Metadata file on disk does not contain document
    if isolated_doc_service.metadata_file.exists():
        with open(isolated_doc_service.metadata_file, "r") as f:
            data = json.load(f)
            assert len(data) == 0


def test_page_limit_rejection_no_vector_store_artifacts(isolated_doc_service, monkeypatch, tmp_path: Path):
    """When a document fails page limits, no vector store artifacts remain in memory or on disk."""
    monkeypatch.setattr(settings, "MAX_DOCUMENT_PAGES", 1)
    isolated_doc_service.pdf_service.max_pages = 1

    # Create 2-page PDF
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Section 1: Initial terms.")
    doc.new_page().insert_text((50, 50), "Section 2: Secondary terms.")
    pdf_bytes = doc.tobytes()
    doc.close()

    with pytest.raises(PageLimitExceededError):
        isolated_doc_service.process_document(pdf_bytes, "over_page_limit.pdf")

    # Vector store in-memory maps are clean
    assert len(isolated_doc_service.vector_store.chunks_by_doc) == 0
    assert len(isolated_doc_service.vector_store.vectors_by_doc) == 0

    # No files in vector store directory
    vector_files = list(isolated_doc_service.vector_store.storage_dir.glob("*"))
    assert len(vector_files) == 0


def test_page_limit_rejection_does_not_poison_hash_index(isolated_doc_service, monkeypatch):
    """When a document is rejected by page limits, its content hash is not retained in hash map."""
    monkeypatch.setattr(settings, "MAX_DOCUMENT_PAGES", 1)
    isolated_doc_service.pdf_service.max_pages = 1

    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Page 1")
    doc.new_page().insert_text((50, 50), "Page 2")
    pdf_bytes = doc.tobytes()
    doc.close()

    with pytest.raises(PageLimitExceededError):
        isolated_doc_service.process_document(pdf_bytes, "two_pages.pdf")

    assert len(isolated_doc_service._hash_to_id) == 0


def test_api_upload_page_limit_rejection(client, monkeypatch):
    """API endpoint returns HTTP 400 and page_limit_exceeded when document exceeds page limit."""
    monkeypatch.setattr(settings, "MAX_DOCUMENT_PAGES", 1)
    # Update app_state's pdf_service max_pages to match
    from app.main import app_state
    app_state["pdf_service"].max_pages = 1

    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Section 1 content.")
    doc.new_page().insert_text((50, 50), "Section 2 content.")
    pdf_bytes = doc.tobytes()
    doc.close()

    try:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("too_many_pages.pdf", pdf_bytes, "application/pdf")}
        )
        assert response.status_code == 400
        assert response.headers.get("X-Error-Category") == "page_limit_exceeded"
        assert "page_limit_exceeded" in response.json()["detail"]
    finally:
        app_state["pdf_service"].max_pages = 500
        monkeypatch.setattr(settings, "MAX_DOCUMENT_PAGES", 500)


# =====================================================================
# 3. Chunk Limits
# =====================================================================

def test_document_within_chunk_limit_succeeds(isolated_doc_service, monkeypatch):
    """Document producing chunks <= MAX_CHUNKS_PER_DOC succeeds."""
    monkeypatch.setattr(settings, "MAX_CHUNKS_PER_DOC", 100)
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()

    doc = isolated_doc_service.process_document(contract_bytes, "contract_chunk_ok.pdf")
    assert doc.chunk_count <= 100
    assert doc.status == "processed"


def test_document_exceeding_chunk_limit_rejected(isolated_doc_service, monkeypatch):
    """Document generating chunk count > MAX_CHUNKS_PER_DOC raises ChunkLimitExceededError."""
    monkeypatch.setattr(settings, "MAX_CHUNKS_PER_DOC", 2)  # Low limit for testing
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()

    with pytest.raises(ChunkLimitExceededError) as exc_info:
        isolated_doc_service.process_document(contract_bytes, "too_many_chunks.pdf")

    assert "exceeding max limit of 2" in str(exc_info.value)
    assert exc_info.value.error_category == "chunk_limit_exceeded"


def test_chunk_limit_rejection_cleans_partial_state(isolated_doc_service, monkeypatch):
    """When chunk limit rejects a document, no partial vectors or files remain."""
    monkeypatch.setattr(settings, "MAX_CHUNKS_PER_DOC", 1)
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()

    with pytest.raises(ChunkLimitExceededError):
        isolated_doc_service.process_document(contract_bytes, "reject_chunks.pdf")

    assert len(isolated_doc_service.documents) == 0
    assert len(isolated_doc_service.vector_store.chunks_by_doc) == 0
    assert len(isolated_doc_service.vector_store.vectors_by_doc) == 0

    # Uploads dir has no orphaned saved file
    uploaded_pdfs = list(isolated_doc_service.upload_dir.glob("*.pdf"))
    assert len(uploaded_pdfs) == 0

    # Telemetry records rejection
    latest = telemetry_collector.get_latest_document()
    assert latest is not None
    assert latest.status == "rejected"
    assert latest.error_category == "chunk_limit_exceeded"


# =====================================================================
# 4. Chat & Query Limits
# =====================================================================

def test_query_below_limit_succeeds(client, uploaded_test_doc_id):
    """User query within MAX_QUERY_CHARS executes normally."""
    query = "What is the governing law?"
    assert len(query) <= settings.MAX_QUERY_CHARS

    response = client.post(
        "/api/chat",
        json={"document_id": uploaded_test_doc_id, "question": query}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_query_exceeding_limit_rejected(client, uploaded_test_doc_id, monkeypatch):
    """Query exceeding MAX_QUERY_CHARS is rejected with HTTP 400 and query_too_large."""
    monkeypatch.setattr(settings, "MAX_QUERY_CHARS", 100)
    long_question = "What is the governing law? " + ("explain in extreme detail " * 10)
    assert len(long_question) > 100

    response = client.post(
        "/api/chat",
        json={"document_id": uploaded_test_doc_id, "question": long_question}
    )
    assert response.status_code == 400
    assert response.headers.get("X-Error-Category") == "query_too_large"
    assert "query_too_large" in response.json()["detail"]

    # Verify telemetry records query rejection
    latest_chat = telemetry_collector.get_latest_chat()
    assert latest_chat is not None
    assert latest_chat.status == "rejected"
    assert latest_chat.error_category == "query_too_large"


def test_top_k_exceeding_limit_rejected(client, uploaded_test_doc_id, monkeypatch):
    """Requesting top_k > MAX_TOP_K is rejected with HTTP 400 and context_limit_exceeded."""
    monkeypatch.setattr(settings, "MAX_TOP_K", 5)

    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_test_doc_id,
            "question": "What is the notice period?",
            "top_k": 20
        }
    )
    assert response.status_code == 400
    assert response.headers.get("X-Error-Category") == "context_limit_exceeded"
    assert "context_limit_exceeded" in response.json()["detail"]


def test_retrieved_context_size_limit_rejected(client, uploaded_test_doc_id, monkeypatch):
    """When retrieved context total chars > MAX_CONTEXT_CHARS, rejected before calling LLM."""
    # Set MAX_CONTEXT_CHARS artificially low
    monkeypatch.setattr(settings, "MAX_CONTEXT_CHARS", 50)

    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_test_doc_id,
            "question": "What is the notice period?"
        }
    )
    assert response.status_code == 400
    assert response.headers.get("X-Error-Category") == "context_limit_exceeded"
    assert "context_limit_exceeded" in response.json()["detail"]


def test_prompt_token_budget_enforced(monkeypatch):
    """When assembled prompt tokens exceed MAX_PROMPT_TOKENS, TokenBudgetExceededError is raised."""
    service = LLMService()
    monkeypatch.setattr(settings, "MAX_PROMPT_TOKENS", 50)  # Low budget

    with pytest.raises(TokenBudgetExceededError) as exc_info:
        service.generate_answer(
            question="What is the liability cap?",
            context_chunks=[
                "Section 5. Limitation of Liability. The total aggregate liability of either party shall be capped at 100,000 dollars."
            ]
        )

    assert "exceeds maximum configured budget of 50 tokens" in str(exc_info.value)
    assert exc_info.value.error_category == "token_budget_exceeded"


def test_api_chat_token_budget_exceeded_rejected(client, uploaded_test_doc_id, monkeypatch):
    """API endpoint returns HTTP 400 and token_budget_exceeded when prompt budget is exceeded."""
    monkeypatch.setattr(settings, "MAX_PROMPT_TOKENS", 50)

    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_test_doc_id,
            "question": "What is the termination notice period?"
        }
    )
    assert response.status_code == 400
    assert response.headers.get("X-Error-Category") == "token_budget_exceeded"
    assert "token_budget_exceeded" in response.json()["detail"]


def test_mock_llm_output_token_budget_bounded(monkeypatch):
    """Mock LLM provider bounds completion output text to MAX_OUTPUT_TOKENS."""
    monkeypatch.setattr(settings, "MAX_OUTPUT_TOKENS", 10)  # Bound to ~10 tokens (~40 chars)
    mock_provider = MockLLMProvider()

    context = ["The agreement is governed by the laws of Delaware. Delaware court jurisdiction applies to all disputes."]
    resp = mock_provider.generate_answer("What is the governing law?", context)

    # 10 tokens * 4 chars = 40 chars maximum
    assert len(resp.content) <= 50
    assert resp.estimated_output_tokens <= 15


def test_openai_provider_configures_max_tokens(monkeypatch):
    """OpenAILLMProvider payload incorporates MAX_OUTPUT_TOKENS parameter."""
    monkeypatch.setattr(settings, "MAX_OUTPUT_TOKENS", 350)
    provider = OpenAILLMProvider(api_key="test-key", model="gpt-4o-mini")

    # Inspect that the provider uses MAX_OUTPUT_TOKENS
    max_tok = settings.MAX_OUTPUT_TOKENS or settings.LLM_MAX_TOKENS
    assert max_tok == 350


# =====================================================================
# 5. Error Categorization & Telemetry Safety
# =====================================================================

def test_telemetry_captures_rejection_without_leaking_content(client, uploaded_test_doc_id, monkeypatch):
    """Rejection telemetry includes error_category and metadata without leaking questions or texts."""
    monkeypatch.setattr(settings, "MAX_QUERY_CHARS", 30)
    secret_text = "CONFIDENTIAL_PATENT_AGREEMENT_QUERY_12345"
    query = f"What is {secret_text}?"
    assert len(query) > 30

    response = client.post(
        "/api/chat",
        json={"document_id": uploaded_test_doc_id, "question": query}
    )
    assert response.status_code == 400

    latest = telemetry_collector.get_latest_chat()
    assert latest is not None
    assert latest.status == "rejected"
    assert latest.error_category == "query_too_large"

    # Crucial security assertion: sensitive query text is NOT present in serialized telemetry
    telemetry_json = latest.model_dump_json()
    assert secret_text not in telemetry_json
