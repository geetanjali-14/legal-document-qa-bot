# Development Plan & Implementation Roadmap
## Legal Document Q&A Assistant

* **Document Version:** 1.0.0
* **Status:** Draft / Execution Plan
* **Author:** Lead Architect & QA Engineering Lead
* **Last Updated:** October 7, 2026

---

## 1. Plan Overview & Guiding Rules

This document outlines the phased roadmap for stabilizing, enhancing, and preparing the **Legal Document Q&A Assistant** for production.

> [!IMPORTANT]
> **Plan Status:** This is a planning and design roadmap. No application source code is to be executed or changed during this documentation phase.

### Current Test Baseline (From Audit)
* **Total Automated Tests:** 11
* **Passing Tests:** 10
* **Failing Tests:** 1 (`tests/integration/test_api_flow.py::test_end_to_end_legal_rag_flow` due to sentence-boundary splitting in `MockLLMProvider`).

---

## 2. Phased Roadmap Summary

```text
Phase 0: Planning & Audit (CURRENT - COMPLETE)
   ↓
Phase 1: Stabilize MVP & Fix Existing Test Baseline (P0)
   ↓
Phase 2: RAG Retrieval & Semantic Quality Upgrades (P1)
   ↓
Phase 3: Conversational Memory & Query Contextualization (P1)
   ↓
Phase 4: Document Ingestion & Legal Clause Parsing (P2)
   ↓
Phase 5: Persistent Relational Storage (P2)
   ↓
Phase 6: Authentication, Authorization & Security Hardening (P1)
   ↓
Phase 7: Additional LLM Providers (Gemini / Anthropic) (P2)
   ↓
Phase 8: Advanced Legal Contract Features (P3)
   ↓
Phase 9: Production Readiness & Observability (P1)
```

---

## 3. Development Tasks by Phase

### Phase 0: Planning & Audit (Current Phase)
* **Objective:** Establish the comprehensive baseline audit, PRD, Technical Architecture, and Development Plan without modifying application code.
* **Status:** Complete.

---

### Phase 1: Stabilize Current MVP Baseline (P0)

#### Task MVP-001: Fix Mock LLM Sentence Splitting Bug
* **Task Name:** Robust Sentence Extraction in Mock LLM Provider
* **Objective:** Resolve the failing assertion in `test_end_to_end_legal_rag_flow` by improving sentence boundary detection in `MockLLMProvider`.
* **Priority:** **P0**
* **Dependencies:** None
* **Files Affected:** [`app/services/llm_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/llm_service.py), [`tests/integration/test_api_flow.py`](file:///home/rails/Work/Legal%20QA%20chatbot/tests/integration/test_api_flow.py)
* **Implementation Notes:** In `MockLLMProvider.generate_answer`, split text using regex `re.split(r'(?<=[.!?])\s+|\n+')` rather than raw `". "` so that clauses separated by newlines or list items retain complete clauses (including numbers like `"30 days"`).
* **Acceptance Criteria:** `pytest` reports 11 passed out of 11 tests.
* **Tests Required:** `tests/integration/test_api_flow.py`

#### Task MVP-002: Verify End-to-End Synthetic Contract Flow
* **Task Name:** End-to-End Contract Q&A Verification
* **Objective:** Confirm full lifecycle (Upload $\to$ Index $\to$ Query $\to$ Citation $\to$ Refusal $\to$ Delete) on the running server.
* **Priority:** **P0**
* **Dependencies:** MVP-001
* **Files Affected:** [`scripts/create_test_pdf.py`](file:///home/rails/Work/Legal%20QA%20chatbot/scripts/create_test_pdf.py), [`tests/e2e/test_live_server.py`](file:///home/rails/Work/Legal%20QA%20chatbot/tests/e2e/test_live_server.py)
* **Acceptance Criteria:** Live server returns HTTP 200 with grounded answers and verifiable citation metadata for all synthetic contract clauses.

---

### Phase 2: RAG Retrieval & Semantic Quality Upgrades (P1)

#### Task RAG-001: Dense Semantic Local Embeddings
* **Task Name:** Integrate Local Dense Embedding Provider
* **Objective:** Replace reliance on TF-IDF token overlap with dense semantic representations running on local CPU without cloud API keys.
* **Priority:** **P1**
* **Dependencies:** MVP-001
* **Files Affected:** [`app/services/embedding_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/embedding_service.py), `requirements.txt`
* **Implementation Notes:** Integrate lightweight `fastembed` (e.g. `BAAI/bge-small-en-v1.5`) as a configurable local provider.
* **Acceptance Criteria:** Synonyms (e.g., query: *"How do I cancel?"*, text: *"terminate the agreement"*) successfully match above similarity threshold.
* **Tests Required:** Semantic synonym retrieval unit test in `tests/unit/test_retrieval_and_store.py`.

#### Task RAG-002: Semantic Reranking & Threshold Tuning
* **Task Name:** Configurable Reranking / Filtering
* **Objective:** Prevent noisy chunks from reaching LLM context when query is ambiguous.
* **Priority:** **P2**
* **Dependencies:** RAG-001
* **Files Affected:** [`app/services/retrieval_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/retrieval_service.py)
* **Acceptance Criteria:** Similarity scores reflect true semantic relevance; precision@3 reaches $>90\%$ on test contract questions.

---

### Phase 3: Conversational Memory & Query Contextualization (P1)

#### Task CHAT-001: Query Reformulation Engine
* **Task Name:** Multi-Turn Conversational Query Rewriting
* **Objective:** Convert follow-up queries containing pronouns (e.g., *"What happens if I don't give it?"*) into standalone search queries before embedding retrieval.
* **Priority:** **P1**
* **Dependencies:** MVP-001
* **Files Affected:** [`app/services/llm_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/llm_service.py), [`app/api/routes_chat.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/api/routes_chat.py)
* **Implementation Notes:** Before invoking `retrieval_service.retrieve`, prompt the LLM to rewrite the question in the context of recent chat history into an independent search query.
* **Acceptance Criteria:** Follow-up questions resolve pronouns and retrieve the appropriate chunks.
* **Tests Required:** Multi-turn integration test in `tests/integration/test_chat_memory.py`.

---

### Phase 4: Document Ingestion & Legal Clause Parsing (P2)

#### Task DOC-001: Scanned Document OCR Pipeline
* **Task Name:** OCR Ingestion Fallback
* **Objective:** Process scanned/image PDFs instead of returning refusal.
* **Priority:** **P2**
* **Dependencies:** MVP-001
* **Files Affected:** [`app/services/pdf_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/pdf_service.py)
* **Implementation Notes:** Integrate `pytesseract` or `pdf2image` when `ScannedPDFError` threshold is triggered.
* **Acceptance Criteria:** Scanned image-only PDFs yield extracted text, correct page indices, and indexed chunks.

#### Task DOC-002: Advanced Legal Clause Boundary Detection
* **Task Name:** Structured Legal Section & Clause Parsing
* **Objective:** Enhance heading regex to preserve nested clause hierarchies (e.g., `Section 4.1(a)`).
* **Priority:** **P2**
* **Dependencies:** None
* **Files Affected:** [`app/services/chunking_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/chunking_service.py)
* **Acceptance Criteria:** Nested legal sub-clauses retain parent section context in metadata.

---

### Phase 5: Persistent Relational Storage (P2)

#### Task DB-001: SQLite / SQLAlchemy Metadata Migration
* **Task Name:** ACID Relational Metadata Store
* **Objective:** Replace flat `documents_meta.json` with an ACID-compliant database.
* **Priority:** **P2**
* **Dependencies:** MVP-001
* **Files Affected:** [`app/services/document_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/document_service.py), [`app/models/document.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/models/document.py)
* **Implementation Notes:** Introduce SQLite with SQLAlchemy or SQLModel for concurrent uploads and metadata queries.
* **Acceptance Criteria:** Concurrent document uploads do not corrupt metadata.

---

### Phase 6: Authentication, Authorization & Security Hardening (P1)

#### Task SEC-001: API Rate Limiting & Origin Hardening
* **Task Name:** Endpoint Rate Limiting & CORS Configuration
* **Objective:** Protect upload and chat routes from resource exhaustion.
* **Priority:** **P1**
* **Dependencies:** MVP-001
* **Files Affected:** [`app/main.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/main.py)
* **Implementation Notes:** Integrate `slowapi` for token-bucket rate limiting and configure whitelist domain origins.
* **Acceptance Criteria:** Exceeding 10 uploads/minute returns HTTP 429 Too Many Requests.

#### Task AUTH-001: User Authentication & Document Ownership
* **Task Name:** Multi-User Tenant Isolation
* **Objective:** Ensure users can only view and query documents they uploaded.
* **Priority:** **P1**
* **Dependencies:** DB-001
* **Files Affected:** New auth router, document service query filters.
* **Acceptance Criteria:** Querying Document ID belonging to User B by User A returns HTTP 403 Forbidden.

---

### Phase 7: Additional LLM Providers (P2)

#### Task LLM-001: Google Gemini LLM & Embedding Integration
* **Task Name:** Google Gemini Provider Implementation
* **Objective:** Implement native Gemini 1.5 Flash/Pro and text-embedding-004 support.
* **Priority:** **P2**
* **Dependencies:** MVP-001
* **Files Affected:** [`app/services/llm_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/llm_service.py), [`app/services/embedding_service.py`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/embedding_service.py)
* **Acceptance Criteria:** Setting `LLM_PROVIDER=gemini` correctly queries Gemini API with strict system prompt and returns citations.

---

### Phase 8: Advanced Legal Contract Features (P3)

#### Task FEAT-001: Multi-Contract Comparison
* **Task Name:** Cross-Document Clause Diffing
* **Objective:** Allow users to select two documents and query differences in specific clauses (e.g. indemnity caps).
* **Priority:** **P3**
* **Dependencies:** Phase 2, Phase 3

---

### Phase 9: Production Readiness & Observability (P1)

#### Task PROD-001: Dockerization & Production Compose Setup
* **Task Name:** Production Containerization
* **Objective:** Package the application into a secure multi-stage Docker container.
* **Priority:** **P1**
* **Dependencies:** MVP-001
* **Files Affected:** `Dockerfile`, `docker-compose.yml`, `README.md`
* **Acceptance Criteria:** Application builds and passes end-to-end tests inside container.

---

## 4. Test Strategy Matrix

| Test Layer | Tools | Scope | Trigger |
|---|---|---|---|
| **Unit Testing** | `pytest` | PDF text cleaning, scan detection, chunking logic, vector store math | Every commit |
| **Integration Testing**| `TestClient`, `pytest-asyncio` | Upload, indexing, scoped vector retrieval, refusal check | Every pull request |
| **RAG Grounding & Hallucination Eval** | Custom synthetic test contracts | Negative question refusal, known clause extraction | Automated CI pipeline |
| **Security Testing** | `pytest` + malicious payloads | Path traversal, oversized files, bad magic bytes | Security regression suite |
| **Live End-to-End** | Uvicorn server + headless browser/client | Full user journey verification | Release gate |

---

## 5. Open Product & Architecture Decisions

Before starting Phase 1 implementation, input is required on the following decisions:

1. **Local vs. Cloud Embeddings Default:**
   * *Option A:* Retain lightweight TF-IDF as default for zero dependencies.
   * *Option B:* Integrate `fastembed` (ONNX-based local embedding) for semantic retrieval without external API keys.
2. **Database Backend Selection:**
   * *Option A:* SQLite via SQLAlchemy (simple, file-based, zero setup, single-instance).
   * *Option B:* PostgreSQL (production-scale, multi-container setup).
3. **Primary LLM Provider for Production:**
   * *Option A:* OpenAI (`gpt-4o-mini`).
   * *Option B:* Google Gemini (`gemini-1.5-flash`).
   * *Option C:* Local model via Ollama.

