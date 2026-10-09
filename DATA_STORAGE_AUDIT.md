# Data Storage Audit — Legal Document QA Assistant

**Audit Date:** 2026-10-09  
**Environment:** Linux (x86_64), Python 3.12, FastAPI  
**Configuration Audited:** `STORAGE_BACKEND=supabase`, `DATABASE_URL` (Neon PostgreSQL), `EMBEDDING_PROVIDER=tfidf`

---

## 1. Data Storage Matrix

| Data | Neon DB | Supabase Storage | Local Storage | Verified Status |
| --- | --- | --- | --- | --- |
| **Original documents** | Not stored (relational metadata only) | Primary remote storage (`legal-qa-documents` bucket) | Cached on upload & retrieval (`data/uploads/<doc_id>_<filename>`) | **Verified**<br>Remote Supabase object `GET 200` verified; local cache in `app/services/storage_service.py` (`SupabaseStorageService.save_file`, `get_file_bytes`). |
| **Document metadata** | Primary table `documents` via `DocumentRecordModel` | Not stored | Synced JSON backup (`data/uploads/documents_meta.json`) | **Verified**<br>`SELECT 1` & record query verified against Neon PostgreSQL in `app/persistence/repository.py` (`save_document_record`, `list_document_records`). Local JSON sync in `app/services/document_service.py`. |
| **Conversations/messages** | Primary tables `conversations`, `messages` | Not stored | Legacy fallback SQLite (`data/legal_qa.db`) if `DATABASE_URL` empty | **Verified**<br>Live session and messages verified in Neon PostgreSQL (`app/persistence/repository.py`: `create_conversation`, `add_message`). Local SQLite preserved as fallback (`app/persistence/database.py`). |
| **Chunks/embeddings/vectors** | Not stored | Not stored | Stored locally in `data/vector_store/` (`_chunks.json`, `_vectors.npy`, `_meta.json`, embedded Qdrant SQLite/WAL `qdrant_db/`) | **Verified (Local Only)**<br>Local disk & embedded Qdrant inspected in `app/services/vector_store.py`. Vectors do NOT upload to Neon or Supabase, but are idempotently rebuilt from persistent storage on startup (`app/main.py:144-155`). |
| **Session ownership** | Stored in `conversations.session_id` column | Not stored | In-memory sliding window rate limiter state (`app/core/security.py`) & client-side HMAC cookie | **Verified**<br>HMAC-SHA256 signed cookie (`legal_qa_session`) verified in `app/core/security.py`. Neon DB records contain `session_id`. Rate limiter history is ephemeral in-memory. |
| **Temporary files/caches** | Not stored | Not stored | Local filesystem: `data/uploads/` local cache, OCR image buffers, in-memory FastAPI upload buffers | **Verified (Local Only)**<br>`LocalStorageService` / `SupabaseStorageService.local_cache_dir` in `app/services/storage_service.py`; PIL/PyMuPDF cache in `app/services/pdf_service.py` and `app/services/image_service.py`. |
| **Sample documents** | Seeded into `documents` table upon demo ingestion | Seeded into bucket upon demo ingestion | Shipped with repository in `documents/` (e.g. `documents/synthetic_contract.pdf`) | **Verified**<br>Source PDF committed locally in `documents/`. Ingested on demand or on `DEMO_MODE=true` startup via content hash matching in `app/main.py:130-141`. |

---

## 2. Persistence & Survival Analysis

### What Survives Restarts
1. **Document Metadata & Schema**: Persists in remote Neon PostgreSQL (`documents` table) and survives container deletion or restarts.
2. **Conversation History & Turns**: Persists in remote Neon PostgreSQL (`conversations`, `messages`, `document_profiles`, `slack_conversation_mappings` tables).
3. **Original Document Files**: Persists in remote Supabase Storage (`legal-qa-documents` bucket). Survives ephemeral container crashes.
4. **Vector Embeddings (via Idempotent Auto-Recovery)**: While the raw `.npy` and local embedded Qdrant files are local/ephemeral, the application lifespan (`app/main.py:144-155`) automatically queries the DB for registered documents and re-indexes missing vector stores from Supabase Storage file bytes upon startup.

### What Remains Local / Ephemeral
1. **Vector Store & Qdrant Cache**: `data/vector_store/` (`*.npy`, `*_chunks.json`, `*_meta.json`, `qdrant_db/`). If an ephemeral filesystem (e.g., Render/Fly.io) is replaced, vector data is lost and must undergo re-embedding on startup.
2. **Local Storage Cache**: `data/uploads/` files are used as a read/write acceleration cache for PyMuPDF/PIL.
3. **In-Memory Rate Limiting & Ephemeral State**: `SlidingWindowRateLimiter._history` resides in Python process memory; resets on app restarts or across multiple container replicas.
4. **SQLite Database**: `data/legal_qa.db` remains local and is only used when `DATABASE_URL` is omitted.

---

## 3. The Three Most Important Actual Gaps

1. **Local-Only Vector Store & Cold Startup Ingestion Latency**:
   - *Issue*: Vectors and chunks are stored only on the local filesystem (`data/vector_store/` and local embedded Qdrant). In serverless or ephemeral container deployments without persistent disks, every restart forces `app/main.py` to re-download all documents from Supabase and re-embed them (incurring cold-start delay and embedding API costs/latency if using cloud embedding models).
   - *Impact*: Scales poorly with document count on ephemeral platforms. Cloud Qdrant or pgvector on Neon is needed for true cloud-native vector persistence.

2. **Dual Metadata Truth (Neon DB vs Local `documents_meta.json`)**:
   - *Issue*: Metadata is written to both Neon DB and local file `data/uploads/documents_meta.json`. Deletions (`doc_service.delete_document`) update both, but if containers scale horizontally or an ephemeral disk restarts with a stale JSON file, conflicting document states can occur between the database and the filesystem JSON.
   - *Impact*: In distributed/multi-worker deployments, `documents_meta.json` can become desynchronized from Neon PostgreSQL.

3. **In-Memory Rate Limiting Across Instances**:
   - *Issue*: Rate limiting in `app/core/security.py` relies on an in-memory dictionary (`SlidingWindowRateLimiter`).
   - *Impact*: Restarts clear the sliding window, and running behind multiple ASGI workers or distributed containers allows users to bypass rate limits across worker processes.

