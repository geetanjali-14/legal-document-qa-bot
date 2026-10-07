import json
import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.document import DocumentMetadata
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService, MockEmbeddingProvider
from app.services.vector_store import VectorStore
from app.core.telemetry import telemetry_collector


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

    pdf_service = PDFService()
    chunking_service = ChunkingService(chunk_size=500, chunk_overlap=100, min_chunk_size=50)
    embedding_service = EmbeddingService()
    embedding_service.provider = MockEmbeddingProvider(dimension=16)
    vector_store = VectorStore(storage_dir=vector_dir)

    service = DocumentService(
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        embedding_service=embedding_service,
        vector_store=vector_store,
        upload_dir=upload_dir
    )
    return service


def test_duplicate_same_bytes_same_filename(isolated_doc_service):
    """
    TEST 1: Same bytes, same filename.
    Verify only one logical document exists and processing is not repeated.
    """
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()

    # First ingestion
    doc1 = isolated_doc_service.process_document(contract_bytes, "synthetic_contract.pdf")
    assert doc1.document_id is not None
    assert doc1.content_hash == hashlib.sha256(contract_bytes).hexdigest()
    assert len(isolated_doc_service.list_documents()) == 1

    # Second ingestion with exact same bytes and filename
    doc2 = isolated_doc_service.process_document(contract_bytes, "synthetic_contract.pdf")
    assert doc2.document_id == doc1.document_id
    assert len(isolated_doc_service.list_documents()) == 1

    # Telemetry check: second upload must be recorded as duplicate reuse
    dup_telem = telemetry_collector.get_latest_document()
    assert dup_telem is not None
    assert dup_telem.is_duplicate is True
    assert dup_telem.status == "duplicate_reused"
    assert dup_telem.extraction_latency_ms == 0.0
    assert dup_telem.chunking_latency_ms == 0.0
    assert dup_telem.embedding_latency_ms == 0.0
    assert dup_telem.indexing_latency_ms == 0.0


def test_duplicate_same_bytes_different_filename(isolated_doc_service):
    """
    TEST 2: Same bytes, different filename.
    Filename MUST NOT determine identity; must resolve to the same document.
    """
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()

    doc_a = isolated_doc_service.process_document(contract_bytes, "contract_a.pdf")
    doc_b = isolated_doc_service.process_document(contract_bytes, "contract_b.pdf")

    assert doc_a.document_id == doc_b.document_id
    assert len(isolated_doc_service.list_documents()) == 1
    # Vector store contains only one index
    assert len(isolated_doc_service.vector_store.chunks_by_doc) == 1


def test_different_bytes_produce_different_identities(isolated_doc_service):
    """
    TEST 3: Different bytes produce distinct documents even if filename is the same.
    """
    contract_bytes_1 = Path("documents/synthetic_contract.pdf").read_bytes()
    # Create valid synthetic PDF bytes with different content
    import fitz
    doc_fitz = fitz.open()
    page = doc_fitz.new_page()
    page.insert_text((72, 72), "Section 1: Completely distinct lease agreement terms.")
    contract_bytes_2 = doc_fitz.tobytes()
    doc_fitz.close()

    doc_1 = isolated_doc_service.process_document(contract_bytes_1, "contract.pdf")
    doc_2 = isolated_doc_service.process_document(contract_bytes_2, "contract.pdf")

    assert doc_1.document_id != doc_2.document_id
    assert doc_1.content_hash != doc_2.content_hash
    assert len(isolated_doc_service.list_documents()) == 2
    assert len(isolated_doc_service.vector_store.chunks_by_doc) == 2


def test_hash_persistence_and_metadata(isolated_doc_service):
    """
    TEST 4: SHA-256 hash is stored and retrievable from document metadata.
    """
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    expected_hash = hashlib.sha256(contract_bytes).hexdigest()

    doc = isolated_doc_service.process_document(contract_bytes, "contract.pdf")
    assert doc.content_hash == expected_hash

    # Verify persisted JSON contains content_hash
    with open(isolated_doc_service.metadata_file, "r", encoding="utf-8") as f:
        meta_json = json.load(f)
    assert meta_json[0]["content_hash"] == expected_hash

    # Verify get_document returns content_hash
    retrieved = isolated_doc_service.get_document(doc.document_id)
    assert retrieved is not None
    assert retrieved.content_hash == expected_hash


def test_api_upload_duplicate_detection(client):
    """
    Verify API endpoint /api/documents/upload behaves correctly on duplicate upload.
    """
    pdf_path = Path("documents/synthetic_contract.pdf")
    with open(pdf_path, "rb") as f:
        res1 = client.post(
            "/api/documents/upload",
            files={"file": ("contract_alpha.pdf", f, "application/pdf")}
        )
    assert res1.status_code == 201
    doc_id_1 = res1.json()["data"]["document_id"]
    content_hash_1 = res1.json()["data"]["content_hash"]
    assert content_hash_1 is not None

    # Upload same bytes under different filename via API
    with open(pdf_path, "rb") as f:
        res2 = client.post(
            "/api/documents/upload",
            files={"file": ("contract_beta.pdf", f, "application/pdf")}
        )
    assert res2.status_code == 201
    doc_id_2 = res2.json()["data"]["document_id"]
    content_hash_2 = res2.json()["data"]["content_hash"]

    # Must resolve to identical document ID and hash
    assert doc_id_1 == doc_id_2
    assert content_hash_1 == content_hash_2

    # Clean up
    client.delete(f"/api/documents/{doc_id_1}")


def test_corrupt_inconsistent_state_fails_safely(isolated_doc_service):
    """
    Edge case: If metadata exists with matching hash but vector store data was deleted/lost,
    fail safely and clearly with RuntimeError instead of returning broken document.
    """
    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    doc = isolated_doc_service.process_document(contract_bytes, "contract.pdf")

    # Simulate catastrophic external deletion or corruption of vector index
    isolated_doc_service.vector_store.delete_document(doc.document_id)

    # Attempting to process identical bytes now detects corrupt state
    with pytest.raises(RuntimeError) as exc_info:
        isolated_doc_service.process_document(contract_bytes, "contract_again.pdf")
    assert "vector data is unexpectedly missing" in str(exc_info.value)


def test_backward_compatibility_backfill_historical_metadata(tmp_path: Path):
    """
    Edge case: Existing document metadata without content_hash is loaded safely
    and backfilled from disk.
    """
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True)
    vector_dir = tmp_path / "vector_store"
    vector_dir.mkdir(parents=True)

    contract_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    test_file = upload_dir / "doc_historical_contract.pdf"
    test_file.write_bytes(contract_bytes)

    # Write historical metadata JSON without 'content_hash'
    meta_record = {
        "document_id": "doc_historical",
        "filename": "doc_historical_contract.pdf",
        "original_filename": "contract.pdf",
        "file_size_bytes": len(contract_bytes),
        "page_count": 3,
        "chunk_count": 9,
        "status": "processed",
        "created_at": "2026-10-06T10:00:00Z"
    }
    meta_file = upload_dir / "documents_meta.json"
    meta_file.write_text(json.dumps([meta_record]), encoding="utf-8")

    pdf_service = PDFService()
    chunking_service = ChunkingService()
    embedding_service = EmbeddingService()
    embedding_service.provider = MockEmbeddingProvider()
    vector_store = VectorStore(storage_dir=vector_dir)

    service = DocumentService(
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        embedding_service=embedding_service,
        vector_store=vector_store
    )
    service.upload_dir = upload_dir
    service.metadata_file = meta_file
    service._load_metadata()

    # Historical document is loaded and content_hash was safely backfilled
    loaded = service.get_document("doc_historical")
    assert loaded is not None
    assert loaded.content_hash == hashlib.sha256(contract_bytes).hexdigest()

