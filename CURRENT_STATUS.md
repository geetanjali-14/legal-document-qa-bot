# CURRENT STATUS

**Last Updated:** 2026-10-09  
**Active Objective:** Persistent data storage milestone (PostgreSQL & Cloudflare R2).

---

### 1. Active Focus
* Persistent data storage architecture: PostgreSQL (Neon) and Cloudflare R2 object storage.
* Idempotent vector recovery from persistent source files.
* Test suite verification and documentation update.

---

### 2. Completed Steps (Verified)
- [x] Fixed conversational follow-up bug for document summaries and legal topics ("Elaborate it more", "In a little precise way", "Make it shorter").
- [x] Integrated Neon PostgreSQL support through SQLAlchemy (`DATABASE_URL` normalization for `postgres://` and `postgresql://`). Retained local SQLite fallback.
- [x] Implemented safe schema evolution: `DocumentRecordModel` (`documents` table) added to models and database migrations.
- [x] Implemented `StorageService` interface with `LocalStorageService` (development) and `CloudflareR2StorageService` (production S3-compatible).
- [x] Implemented idempotent vector store rebuild from persistent storage files on application startup.
- [x] Verified HMAC session security and strict ownership isolation unchanged.
- [x] Blocked uploads in `DEMO_MODE=True` (returns HTTP 403) while allowing sample document browsing.
- [x] Verified full regression test suite:
  * Conversational Follow-ups: `tests/unit/test_conversational_followups.py` (4 passed in 7.77s).
  * Persistence & Storage: `tests/unit/test_persistence_and_storage.py` (7 passed in 1.11s).
  * Demo Safeguards: `tests/unit/test_demo_safeguards.py` (7 passed in 2.36s).
- [x] Updated `.env.example`, `PROJECT_CONTEXT.md`, and `CURRENT_STATUS.md`.

---

### 3. Blockers & Unresolved Issues
* None. All tests passing. Ready to push changes.

---

### 4. Immediate Next Action
* Push committed changes to remote repository.
