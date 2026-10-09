# CURRENT STATUS

**Last Updated:** 2026-10-09  
**Active Objective:** Persistent data storage with Supabase Storage & Neon PostgreSQL.

---

### 1. Active Focus
* Supabase Storage integration replacing Cloudflare R2 behind the unified `StorageService` interface.
* Preservation of local filesystem storage, vector recovery, and session isolation.

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
- [x] Verified test suite:
  * Persistence & Storage: `tests/unit/test_persistence_and_storage.py` (8 passed in 1.32s).
  * Demo Safeguards: `tests/unit/test_demo_safeguards.py` (7 passed in 1.00s).
  * Security & Hardening: `tests/unit/test_security_and_hardening.py` (10 passed in 27.82s).
  * Retrieval & Store: `tests/unit/test_retrieval_and_store.py` (2 passed in 0.12s).
- [x] Updated `memory.md`, `PROJECT_CONTEXT.md`, and `CURRENT_STATUS.md`.

---

### 3. Blockers & Unresolved Issues
* None. All 27 focused unit tests passing cleanly.

---

### 4. Immediate Next Action
* Report implementation and verification results to user.
