# CURRENT STATUS

**Last Updated:** 2026-10-09  
**Active Objective:** Persistent data storage with Supabase Storage & Neon PostgreSQL.

---

### 1. Active Focus
* Supabase Storage integration replacing Cloudflare R2 behind the unified `StorageService` interface.
* Preservation of local filesystem storage, vector recovery, and session isolation.

---

### 2. Completed Steps (Verified)
- [x] Fixed conversational follow-up bug for document summaries and legal topics ("Elaborate it more", "In a little precise way", "Make it shorter").
- [x] Integrated Neon PostgreSQL support through SQLAlchemy (`DATABASE_URL` normalization). Retained local SQLite fallback.
- [x] Implemented safe schema evolution: `DocumentRecordModel` (`documents` table) added to models and database migrations.
- [x] Implemented `SupabaseStorageService` behind `StorageService` interface with `STORAGE_BACKEND=local|supabase` and config (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET_NAME`).
- [x] Preserved local filesystem storage (`LocalStorageService`) for zero-friction development and offline testing.
- [x] Preserved idempotent vector store rebuild from persistent storage files on application startup.
- [x] Verified full regression test suite:
  * Persistence & Storage: `tests/unit/test_persistence_and_storage.py` (7 passed in 0.83s).
  * Demo Safeguards: `tests/unit/test_demo_safeguards.py` (7 passed in 2.36s).
  * Full Regression: 34 passed in 17.36s (`tests/unit/test_persistence_and_storage.py`, `tests/unit/test_demo_safeguards.py`, `tests/integration/`, `tests/unit/test_security_and_hardening.py`, `tests/unit/test_retrieval_and_store.py`).
- [x] Updated `.env.example`, `PROJECT_CONTEXT.md`, and `CURRENT_STATUS.md`.

---

### 3. Blockers & Unresolved Issues
* None. All 34 tests passing cleanly.

---

### 4. Immediate Next Action
* Push committed changes to remote repository.
