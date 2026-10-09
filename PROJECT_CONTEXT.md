# Project Context — Legal QA Assistant

> **Single Source of Truth** for project architecture, stack, state, and operational context.  
> Read this file **first** before starting any new task. Update it incrementally after completing verified work.

---

## 1. Project Purpose & High-Level Overview

* **Application**: Legal Document Q&A Assistant.
* **Goal**: Enable users to upload legal PDFs and contracts, parse structure (articles, sections, clauses), and ask grounded questions with strict page, clause, section, and snippet citations.
* **Core Value**: Grounded legal retrieval, hallucination minimization, multi-turn conversational reasoning, multi-platform integrations (Web UI, REST API v1, Slack Bolt bot), and production/demo security safeguards.

---

## 2. Tech Stack & Dependencies

* **Language & Runtime**: Python 3.12 (virtualenv at `./venv`).
* **Backend Framework**: FastAPI with Starlette, Uvicorn ASGI server.
* **Database / Storage**:
  * SQLite with WAL mode (`data/legal_qa.db`) via `sqlite3` and custom SQL repository (`app/persistence/repository.py`).
  * Pluggable PostgreSQL support (`DATABASE_URL`).
  * Document upload directory: `data/uploads/` with metadata index in `data/uploads/documents_meta.json`.
* **Vector Store & Retrieval**:
  * Local in-memory numpy cosine similarity store with `.npy` matrix and `_chunks.json` serialization (`app/services/vector_store.py`).
  * Qdrant provider integration (`app/providers/vector/qdrant.py`).
  * Hybrid retrieval: Dense semantic vectors + BM25 keyword search fused via Reciprocal Rank Fusion (RRF) (`app/services/retrieval_service.py`).
* **Embeddings**: Pluggable (`app/services/embedding_service.py`): Gemini Embedding 2, FastEmbed, TF-IDF (local fallback), OpenAI, Mock.
* **LLM Engine**: Pluggable (`app/services/llm_service.py`): Groq (`llama-3.3-70b-versatile`), Gemini (`gemini-2.5-flash`), OpenAI (`gpt-4o-mini`), Mock.
* **Document Parsing**:
  * PyMuPDF (`fitz` / `pymupdf`) for direct text/PDF extraction (`app/services/pdf_service.py`).
  * RapidOCR (`rapidocr_onnxruntime`) for scanned document image OCR (`app/services/image_service.py`).
  * Structural hierarchy regex parser (`app/services/structure_parser.py`).
* **Integrations & Frontend**:
  * Modern vanilla JS web dashboard (`frontend/` mounted via FastAPI static files).
  * Slack Bolt SDK adapter (`app/integrations/slack/`) connected to versioned API namespace (`/api/v1`).

---

## 3. Architecture & Data Flow

```text
User Question / API / Slack Request
                │
                ▼
      [app/api/ (or /api/v1)]
  - Demo Safeguards & Rate Limiting (app/core/security.py)
  - Validation (Query length, Top-K bounds, File isolation)
                │
                ▼
      [app/services/agent_orchestrator.py]
  - Query Contextualization & Pronoun Resolution
  - Intent Routing (7 operational intents)
  - Tool Execution Branch:
      ├── Metadata / Profile / Navigation Tools (Deterministic)
      └── Substantive Evidence Search
                │
                ▼
      [app/services/retrieval_service.py]
  - Hybrid Search: Dense + BM25 with Reciprocal Rank Fusion
  - Relevance Gate & Identifier-boosted Reranker
  - Deduplication
                │
                ▼
      [app/services/llm_service.py]
  - Grounded Synthesis with Legal Reasoning Modules:
      (ConflictDetector, TemporalReasoner, ObligationExtractor, RiskAnalyzer)
  - Citation Validation & Verification (CitationService)
                │
                ▼
      [Response & SQLite/Postgres Persistence]
  - Telemetry & Turn Storage (app/persistence/repository.py)
```

---

## 4. Key Directories & Important Files

* `app/main.py`: Application factory, middleware setup, CORS, lifespan, and static mounting.
* `app/core/`:
  * `config.py`: Pydantic settings loading from environment variables.
  * `security.py`: Demo safeguards, IP-based rate limiting, read-only mode, and session isolation.
  * `logging.py` & `telemetry.py`: Request logging, metrics, latency, and token counters.
* `app/api/`:
  * `routes_chat.py`: `/api/chat` interactive multi-turn endpoints.
  * `routes_documents.py`: Document upload, listing, details, and deletion.
  * `routes_conversations.py`: Multi-turn session management.
  * `routes_health.py`: Readiness/liveness health checks.
  * `v1/router.py`: Decoupled `/api/v1` namespace for external clients (e.g. Slack bot).
* `app/services/`:
  * `agent_orchestrator.py`: Multi-turn conversational controller, intent router, and tool orchestrator.
  * `retrieval_service.py`: Hybrid search, RRF rank fusion, relevance gating, and reranking.
  * `chunking_service.py`: Legal structure-aware document chunking with metadata tagging.
  * `structure_parser.py`: Extraction of articles, sections, definitions, and cross-references.
  * `llm_service.py`: Abstracted provider interface for Groq, Gemini, OpenAI, Mock.
  * `citation_validator.py` & `citation_service.py`: Source ground checking and snippet citation matching.
* `app/persistence/`:
  * `database.py`: DB connection management (SQLite / PostgreSQL).
  * `repository.py`: CRUD queries for documents, conversations, turns, and demo sessions.
* `app/integrations/slack/`: Slack Bolt socket mode bot running against `/api/v1`.

---

## 5. Configuration & Environment Variables (No Secrets)

All configuration keys defined in `.env.example`:
* **App Basics**: `APP_NAME`, `APP_ENV`, `DEBUG`, `PORT`, `HOST`
* **Demo Safeguards**: `DEMO_MODE`, `SESSION_SECRET`, `RATE_LIMIT_CHAT_PER_MINUTE`, `RATE_LIMIT_CONV_PER_MINUTE`
* **Storage Paths**: `UPLOAD_DIR`, `VECTOR_STORE_DIR`, `DATABASE_PATH`, `DATABASE_URL`, `MAX_FILE_SIZE_MB`, `MAX_CHUNKS_PER_DOC`
* **RAG / Chunking**: `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MIN_CHUNK_SIZE`, `TOP_K`, `SIMILARITY_THRESHOLD`
* **LLM & Embeddings**: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `EMBEDDING_PROVIDER`, `EMBEDDING_API_KEY`
* **Slack**: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `LEGAL_QA_API_BASE_URL`

*(Notice: Never commit `.env` or write live API keys into persistent documents.)*

---

## 6. Key Implementation Decisions & Rationale

1. **Hybrid Retrieval with Reciprocal Rank Fusion (RRF)**:
   * *Reason*: Pure vector search often misses specific legal section numbers (e.g. "Section 14.2(b)") and legal boilerplate; BM25 ensures exact keyword/code retrieval while dense embeddings capture conceptual semantic meaning.
2. **Structure-Aware Chunking over Fixed-Length**:
   * *Reason*: Splitting legal documents by arbitrary token counts breaks clause semantics and obligations. Chunking respects Article, Section, and Definition boundaries.
3. **Deterministic Tools Prioritized Before LLM**:
   * *Reason*: Queries like "What is the document title?", "List sections", or "Who are the parties?" execute via 0-token deterministic metadata lookups, saving tokens and eliminating hallucinations.
4. **Session-Isolated Demo Safeguards**:
   * *Reason*: When `DEMO_MODE=true`, uploads and conversation histories are isolated per browser session via cryptographic HMAC-SHA256 signed cookies (`legal_qa_session`), preventing public test users from seeing or deleting each other's data. Legacy conversation records without session IDs are strictly isolated from new sessions.
56. **Idempotent Sample Seeding & Schema Migration**:
   * *Reason*: On Render/ephemeral restarts, sample documents from `documents/` are checked by SHA-256 content hash before re-indexing, preventing duplicate records or vectors. Database initialization safely inspects both SQLite `PRAGMA table_info` and PostgreSQL `information_schema.columns` to ensure `session_id` exists without table drops.
7. **Persistent Data Storage Architecture (Neon PostgreSQL + pgvector & Supabase Storage)**:
   * *Reason*: Neon PostgreSQL is the single source of truth for both relational entities (`documents`, `conversations`, `messages`, `document_profiles`, `slack_conversation_mappings`) and chunk vector embeddings (`document_chunks` table via `pgvector`). Document source files persist in private Supabase Storage via `SupabaseStorageService` behind the abstract `StorageService` interface (`STORAGE_BACKEND=local|supabase`). Local vector store files and caches are disposable; VectorStore loads directly from Neon DB on application startup or cold container deployment.

---

## 7. Verification & Testing Standards

* **Test Execution**: Always run with virtual environment Python and `PYTHONPATH=.`:
  ```bash
  PYTHONPATH=. ./venv/bin/pytest <path-to-test>
  ```
* **Recently Verified Test Results**:
  * `tests/unit/test_persistence_and_storage.py`: **8 passed in 1.32s** (SQLite/Neon PostgreSQL URL normalization, DocumentRecord DB persistence, LocalStorageService, Supabase Storage service with mock, durable vector chunk persistence in DB, and restart recovery from empty local store).
  * `tests/unit/test_demo_safeguards.py`: **7 passed in 1.00s** (Upload blocking, document deletion blocking, cross-session isolation, rate limiting, HMAC cookie signature protection, legacy record isolation, and idempotent sample seeding).
  * `tests/unit/test_security_and_hardening.py`: **10 passed in 27.82s**.
  * `tests/unit/test_retrieval_and_store.py`: **2 passed in 0.12s**.
* **Cleanup Rule**: Any test data, temporary PDF, or dummy database records created during test execution must be cleaned up immediately.

---

## 8. Current Status & Known Risks

* **Active Objective**: Production-ready durable persistence via Neon PostgreSQL + pgvector and Supabase Storage verified.
* **Known Risks & Configuration Distinctions**:
  * **Verified Locally**: SQLite & PostgreSQL URL normalization, DocumentRecord & DocumentChunkModel DB models/migrations, LocalStorageService, Supabase Storage service, durable vector chunk recovery without local files, HMAC session isolation, and demo safeguards.
  * **Verified Live Cloud**: Neon PostgreSQL (`CREATE EXTENSION IF NOT EXISTS vector;`, `documents` table, `document_chunks` table with pgvector, `conversations`, `messages`), and Supabase Storage bucket (`legal-qa-documents`).
  * In-memory sliding window rate limits protect bursts (`RATE_LIMIT_CHAT_PER_MINUTE=15`) per container lifetime, but do not constitute an external global LLM spend cap if containers restart or across distributed workers.
  * Pytest requires explicit `PYTHONPATH=.` when invoked via `./venv/bin/pytest`.
