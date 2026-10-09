import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from app.core.config import settings
from app.persistence.database import DatabaseManager
from app.persistence.repository import ConversationRepository
from app.services.storage_service import LocalStorageService, SupabaseStorageService
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import MockEmbeddingProvider, EmbeddingService
from app.services.vector_store import VectorStore


@pytest.fixture
def temp_dirs():
    tmp_path = Path(tempfile.mkdtemp(prefix="test_storage_"))
    upload_dir = tmp_path / "uploads"
    vector_dir = tmp_path / "vector_store"
    db_path = tmp_path / "test.db"
    upload_dir.mkdir(parents=True, exist_ok=True)
    vector_dir.mkdir(parents=True, exist_ok=True)
    yield {"tmp": tmp_path, "uploads": upload_dir, "vectors": vector_dir, "db": db_path}
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_sqlite_and_postgres_url_initialization(temp_dirs, monkeypatch):
    """Verify DatabaseManager supports SQLite and PostgreSQL connection schemes."""
    # SQLite
    db_mgr = DatabaseManager(db_path=temp_dirs["db"])
    assert db_mgr.session_factory is not None

    # PostgreSQL schema handling (mocking create_engine)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgres://user:pass@ep-cool-db.us-east-2.aws.neon.tech/neondb?sslmode=require")
    from unittest.mock import patch
    with patch("app.persistence.database.create_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_conn.exec_driver_sql.return_value.fetchall.return_value = []
        mock_conn.exec_driver_sql.return_value.scalar.return_value = 1
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_engine.return_value.begin.return_value.__enter__.return_value = mock_conn

        db_mgr_pg = DatabaseManager(db_path=temp_dirs["db"])
        assert db_mgr_pg is not None
        # Verify normalization of postgres:// to postgresql+psycopg2:// or postgresql://
        passed_url = mock_engine.call_args[0][0]
        assert passed_url.startswith("postgresql")


def test_document_record_persistence_in_db(temp_dirs):
    """Verify document metadata persists and queryable via ConversationRepository."""
    db_mgr = DatabaseManager(db_path=temp_dirs["db"])
    repo = ConversationRepository(session_factory=db_mgr.session_factory)

    doc_data = {
        "document_id": "doc_test123",
        "filename": "doc_test123_agreement.pdf",
        "original_filename": "agreement.pdf",
        "file_size_bytes": 1024,
        "page_count": 2,
        "chunk_count": 4,
        "content_hash": "hash_abc_123",
        "document_type": "contract",
        "embedding_provider": "tfidf",
        "embedding_model": "tfidf-scikit",
        "embedding_dimension": 128
    }

    rec = repo.save_document_record(doc_data)
    assert rec.document_id == "doc_test123"

    # Query back
    fetched = repo.get_document_record("doc_test123")
    assert fetched is not None
    assert fetched.content_hash == "hash_abc_123"

    by_hash = repo.find_document_record_by_hash("hash_abc_123")
    assert by_hash is not None
    assert by_hash.document_id == "doc_test123"

    docs = repo.list_document_records()
    assert len(docs) == 1
    assert docs[0].document_id == "doc_test123"

    # Delete
    deleted = repo.delete_document_record("doc_test123")
    assert deleted is True
    assert repo.get_document_record("doc_test123") is None


def test_local_storage_service(temp_dirs):
    """Verify local storage service operations."""
    storage = LocalStorageService(base_dir=temp_dirs["uploads"])
    content = b"%PDF-1.4 test document binary"
    name = "test_doc.pdf"

    saved_name = storage.save_file(name, content)
    assert saved_name == name
    assert storage.file_exists(name) is True
    assert storage.get_file_bytes(name) == content
    assert storage.get_local_path(name) == temp_dirs["uploads"] / name

    assert storage.delete_file(name) is True
    assert storage.file_exists(name) is False
    assert storage.get_file_bytes(name) is None


def test_supabase_storage_service_mocked(temp_dirs):
    """Verify Supabase Storage operations using mocked HTTP client."""
    mock_http = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_http.post.return_value = mock_post_resp

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.content = b"%PDF-1.4 supabase content bytes"
    mock_http.get.return_value = mock_get_resp

    mock_del_resp = MagicMock()
    mock_del_resp.status_code = 200
    mock_http.delete.return_value = mock_del_resp

    supabase_storage = SupabaseStorageService(
        supabase_url="https://xyzcompany.supabase.co",
        service_key="fake-service-key",
        bucket_name="legal-documents",
        local_cache_dir=temp_dirs["uploads"],
        http_client=mock_http
    )

    # Save
    saved = supabase_storage.save_file("contract.pdf", b"%PDF-1.4 supabase content bytes")
    assert saved == "contract.pdf"
    mock_http.post.assert_called_once()
    assert "https://xyzcompany.supabase.co/storage/v1/object/legal-documents/contract.pdf" in mock_http.post.call_args[0][0]

    # File exists check
    assert supabase_storage.file_exists("contract.pdf") is True

    # Get file bytes
    retrieved_bytes = supabase_storage.get_file_bytes("contract.pdf")
    assert retrieved_bytes == b"%PDF-1.4 supabase content bytes"

    # Delete
    deleted = supabase_storage.delete_file("contract.pdf")
    assert deleted is True
    mock_http.delete.assert_called_once()
    assert "https://xyzcompany.supabase.co/storage/v1/object/legal-documents/contract.pdf" in mock_http.delete.call_args[0][0]


def test_idempotent_vector_rebuild_from_persistent_storage(temp_dirs):
    """
    Verify that when vector files are wiped/missing, document can be
    re-indexed idempotently from persistent storage files without data duplication.
    """
    db_mgr = DatabaseManager(db_path=temp_dirs["db"])
    repo = ConversationRepository(session_factory=db_mgr.session_factory)
    storage = LocalStorageService(base_dir=temp_dirs["uploads"])

    vector_store = VectorStore(storage_dir=temp_dirs["vectors"])
    emb_service = EmbeddingService()
    emb_service.provider = MockEmbeddingProvider(dimension=128)

    doc_service = DocumentService(
        pdf_service=PDFService(),
        chunking_service=ChunkingService(chunk_size=200, chunk_overlap=50),
        embedding_service=emb_service,
        vector_store=vector_store,
        upload_dir=temp_dirs["uploads"],
        storage_service=storage,
        repository=repo
    )

    # Ingest a real sample PDF from documents/
    sample_pdf_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    meta = doc_service.process_document(sample_pdf_bytes, "synthetic_contract.pdf")
    doc_id = meta.document_id

    assert vector_store.has_document(doc_id) is True
    assert repo.get_document_record(doc_id) is not None

    # Simulate vector storage wipe (like container restart without vector volume)
    vector_store.delete_document(doc_id)
    assert vector_store.has_document(doc_id) is False

    # Metadata and file still persist in repo + storage
    assert repo.get_document_record(doc_id) is not None
    assert storage.file_exists(meta.filename) is True

    # Re-index from persistent file bytes
    file_bytes = storage.get_file_bytes(meta.filename)
    rebuilt_meta = doc_service.process_document(file_bytes, meta.original_filename)

    # Vector store recovered with preserved document_id
    assert rebuilt_meta.document_id == doc_id
    assert vector_store.has_document(doc_id) is True

    # Retrieval after recovery works end-to-end
    from app.services.retrieval_service import RetrievalService
    retrieval = RetrievalService(emb_service, vector_store)
    results = retrieval.retrieve(doc_id, "agreement terms and liability", top_k=2, threshold=0.0)
    assert len(results) > 0
    assert results[0][0].document_id == doc_id


def test_delete_document_end_to_end_cleanup(temp_dirs):
    """Verify that deleting a document consistently removes file, DB metadata, and vectors."""
    db_mgr = DatabaseManager(db_path=temp_dirs["db"])
    repo = ConversationRepository(session_factory=db_mgr.session_factory)
    storage = LocalStorageService(base_dir=temp_dirs["uploads"])

    vector_store = VectorStore(storage_dir=temp_dirs["vectors"])
    emb_service = EmbeddingService()
    emb_service.provider = MockEmbeddingProvider(dimension=128)

    doc_service = DocumentService(
        pdf_service=PDFService(),
        chunking_service=ChunkingService(chunk_size=200, chunk_overlap=50),
        embedding_service=emb_service,
        vector_store=vector_store,
        upload_dir=temp_dirs["uploads"],
        storage_service=storage,
        repository=repo
    )

    sample_pdf_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    meta = doc_service.process_document(sample_pdf_bytes, "synthetic_contract.pdf")
    doc_id = meta.document_id

    assert storage.file_exists(meta.filename) is True
    assert repo.get_document_record(doc_id) is not None
    assert vector_store.has_document(doc_id) is True

    # Delete
    deleted = doc_service.delete_document(doc_id)
    assert deleted is True

    # Assert all three layers are cleaned up
    assert storage.file_exists(meta.filename) is False
    assert repo.get_document_record(doc_id) is None
    assert vector_store.has_document(doc_id) is False
    assert doc_service.get_document(doc_id) is None


def test_duplicate_upload_detection_and_vector_loss_recovery(temp_dirs):
    """
    Verify duplicate upload detects existing metadata and avoids duplicate vectors,
    while allowing re-indexing if vectors were lost.
    """
    db_mgr = DatabaseManager(db_path=temp_dirs["db"])
    repo = ConversationRepository(session_factory=db_mgr.session_factory)
    storage = LocalStorageService(base_dir=temp_dirs["uploads"])

    vector_store = VectorStore(storage_dir=temp_dirs["vectors"])
    emb_service = EmbeddingService()
    emb_service.provider = MockEmbeddingProvider(dimension=128)

    doc_service = DocumentService(
        pdf_service=PDFService(),
        chunking_service=ChunkingService(chunk_size=200, chunk_overlap=50),
        embedding_service=emb_service,
        vector_store=vector_store,
        upload_dir=temp_dirs["uploads"],
        storage_service=storage,
        repository=repo
    )

    sample_pdf_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    doc1 = doc_service.process_document(sample_pdf_bytes, "contract1.pdf")
    doc_id = doc1.document_id
    initial_chunks = len(vector_store.chunks_by_doc[doc_id])

    # 1. Duplicate upload with intact vectors -> reuses existing document without duplicating vectors
    doc2 = doc_service.process_document(sample_pdf_bytes, "contract2.pdf")
    assert doc2.document_id == doc_id
    assert len(vector_store.chunks_by_doc[doc_id]) == initial_chunks
    assert len(doc_service.list_documents()) == 1

    # 2. Simulate vector loss (vectors missing, but DB and file persist)
    vector_store.delete_document(doc_id)
    assert vector_store.has_document(doc_id) is False
    assert repo.get_document_record(doc_id) is not None

    # Re-uploading or processing recovers vectors under the same document ID
    doc3 = doc_service.process_document(sample_pdf_bytes, "contract1.pdf")
    assert doc3.document_id == doc_id
    assert vector_store.has_document(doc_id) is True
    assert len(vector_store.chunks_by_doc[doc_id]) == initial_chunks
    assert len(doc_service.list_documents()) == 1


def test_durable_vector_chunk_persistence_and_restart_recovery(temp_dirs):
    """
    Verify that chunks and vectors are persisted to the database repository,
    and a fresh VectorStore with a completely clean/empty local directory
    successfully restores all chunks and vectors directly from the database without re-embedding.
    """
    db_mgr = DatabaseManager(db_path=temp_dirs["db"])
    repo = ConversationRepository(session_factory=db_mgr.session_factory)
    storage = LocalStorageService(base_dir=temp_dirs["uploads"])

    vector_store = VectorStore(storage_dir=temp_dirs["vectors"], repository=repo)
    emb_service = EmbeddingService()
    emb_service.provider = MockEmbeddingProvider(dimension=128)

    doc_service = DocumentService(
        pdf_service=PDFService(),
        chunking_service=ChunkingService(chunk_size=200, chunk_overlap=50),
        embedding_service=emb_service,
        vector_store=vector_store,
        upload_dir=temp_dirs["uploads"],
        storage_service=storage,
        repository=repo
    )

    sample_pdf_bytes = Path("documents/synthetic_contract.pdf").read_bytes()
    doc = doc_service.process_document(sample_pdf_bytes, "synthetic_contract.pdf")
    doc_id = doc.document_id

    # 1. Verify chunks are persisted in database
    db_chunks = repo.get_document_chunks(doc_id)
    assert len(db_chunks) > 0
    assert len(db_chunks) == len(vector_store.chunks_by_doc[doc_id])

    # 2. Simulate fresh container deployment: wipe local vector_store directory completely
    fresh_vector_dir = temp_dirs["tmp"] / "fresh_vector_store"
    fresh_vector_dir.mkdir(parents=True, exist_ok=True)

    # Instantiate brand new VectorStore pointing to fresh directory, connected to the same DB repo
    recovered_vector_store = VectorStore(storage_dir=fresh_vector_dir, repository=repo)

    # 3. Verify chunks and vectors restored immediately from DB without local files
    assert recovered_vector_store.has_document(doc_id) is True
    assert len(recovered_vector_store.chunks_by_doc[doc_id]) == len(db_chunks)

    # 4. Verify search and retrieval works on recovered vector store
    from app.services.retrieval_service import RetrievalService
    retrieval = RetrievalService(emb_service, recovered_vector_store)
    hits = retrieval.retrieve(doc_id, "agreement terms liability", top_k=2, threshold=0.0)
    assert len(hits) > 0
    assert hits[0][0].document_id == doc_id


