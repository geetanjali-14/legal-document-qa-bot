# CURRENT STATUS

**Last Updated:** 2026-10-09  
**Active Objective:** Production deployment — Neon PostgreSQL + pgvector as sole durable vector store.

---

### 1. Active Focus
* Deployment readiness: ensure Neon pgvector is the actual retrieval source of truth when `DATABASE_URL` is configured.

---

### 2. Completed Steps (Verified)
- [x] Fixed conversational follow-up bug for document summaries and legal topics.
- [x] Integrated Neon PostgreSQL support through SQLAlchemy (`DATABASE_URL` normalization). Retained local SQLite fallback.
- [x] Implemented safe schema evolution: `DocumentRecordModel` (`documents` table) and `DocumentChunkModel` (`document_chunks` table via `pgvector`).
- [x] Made Neon PostgreSQL the single source of truth for document metadata; removed normal-operation dependence on `documents_meta.json`.
- [x] Implemented durable chunk and vector persistence in Neon DB via `pgvector` with local in-memory/Qdrant acceleration cache.
- [x] Integrated `SupabaseStorageService` behind `StorageService` interface with `STORAGE_BACKEND=local|supabase`. Original PDFs persist in private Supabase Storage (`legal-qa-documents` bucket); local cache and Qdrant files are treated as disposable.
- [x] Verified full restart and recovery: fresh `VectorStore` instances load chunks directly from DB repository on startup without requiring local files or re-embedding.
- [x] Verified HMAC session isolation and demo upload restrictions.
- [x] **Fixed production Qdrant initialization bug** (`app/services/vector_store.py`):
  * Root cause: `VectorStore.__init__` unconditionally created `qdrant_db/` on disk and initialized a file-based `QdrantClient` regardless of `DATABASE_URL`. `_load_all_persisted()` also read local `.npy`/`_chunks.json` files even when pgvector was configured.
  * Fix: When `DATABASE_URL` contains a PostgreSQL URL (`postgres://` or `postgresql://`), `VectorStore` now uses in-memory Qdrant only as an acceleration cache, skips `qdrant_db/` directory creation, skips local disk file loading, and skips disk writes in `add_document()`. Local filesystem path is only taken when `DATABASE_URL` is absent (local dev/SQLite mode).
  * Verified: 10 focused tests passed (persistence, retrieval); spot-checks confirmed correct log output for both URL forms and local dev path.
- [x] Verified test suite:
  * Persistence & Storage: `tests/unit/test_persistence_and_storage.py` (8 passed in 0.71s).
  * Retrieval & Store: `tests/unit/test_retrieval_and_store.py` (2 passed in 0.71s).
  * Demo Safeguards: `tests/unit/test_demo_safeguards.py` (7 passed in 1.00s — prior run).
  * Security & Hardening: `tests/unit/test_security_and_hardening.py` (10 passed in 27.82s — prior run).
- [x] Updated `memory.md`, `PROJECT_CONTEXT.md`, and `CURRENT_STATUS.md`.

---

### 3. Blockers & Unresolved Issues
* None. App is safe for Render's disposable filesystem when `DATABASE_URL` is configured.

---

### 4. Immediate Next Action
* Deploy to Render. Confirm startup logs show the pgvector path, not `qdrant_db` initialization.
