# Development Plan & Implementation Roadmap
## Agentic Legal Document Intelligence Application

* **Document Version:** 4.0.0
* **Status:** Functional MVP with known RAG correctness gap; Final Implementation Plan.
* **Current Priority:** Implement and verify the Hybrid RAG Core in the existing FastAPI application.
* **Author:** Lead Architect & QA Engineering Lead
* **Last Updated:** October 8, 2026

---

## 1. Executive Summary & Principles

This implementation plan governs the upgrade of the **Legal Document Intelligence Application** from its legacy heuristic retrieval state to the target **Docling + Structure-Aware Chunking + Gemini Embedding 2 + Local Qdrant + BM25 + RRF + Question Routing + Gemini 3.8 Flash** architecture.

### Core Principles
1. **Existing Application Context:** All work takes place directly within the existing FastAPI backend (`app/`) and frontend (`frontend/`). We do **NOT** create a separate RAG project or lab.
2. **Provider-Independent Retrieval:** The hybrid retrieval engine produces a standardized evidence representation consumable by any configured LLM provider.
3. **No Premature Complexity:** Reranking is explicitly deferred until the hybrid retrieval baseline is verified.
4. **Verification Over Green Lights:** A passing synthetic benchmark or HTTP 200 does not equal real-world correctness. The RAG pipeline is successful only when real legal contracts (e.g., Rental Agreements) retrieve accurate clauses and annexures.

---

## 2. Implementation Phases & Work Breakdown

```text
Phase 0: Current-State Audit
   ↓
Phase 1: Document Ingestion Replacement (Docling)
   ↓
Phase 2: Structure-Aware Legal Chunking
   ↓
Phase 3: Gemini Embeddings + Local Qdrant
   ↓
Phase 4: Hybrid Retrieval (Dense + BM25 + RRF)
   ↓
Phase 5: Question Routing (General vs. Document)
   ↓
Phase 6: Gemini 3.8 Flash Answer Generation & Grounding
   ↓
Phase 7: Real-Document Validation Suite
   ↓
Phase 8: Retrieval & Answer Evaluation Benchmark
   ↓
Phase 9: Reranking (DEFERRED)
   ↓
Phase 10: Production Hardening
```

---

### PHASE 0 — Current-State Audit
* **Scope:**
  * Audit existing ingestion (`app/services/pdf_service.py`), chunking (`app/services/chunking_service.py`), retrieval (`app/services/retrieval_service.py`), vector store (`app/services/vector_store.py`), and agent orchestrator (`app/services/agent_orchestrator.py`).
  * Trace the actual execution path for ingestion $\to$ retrieval $\to$ answer generation.
  * Identify exact failure points causing document questions to fail on real contracts (e.g. miss on ANNEXURE-I, generic clause mix-up).
  * Identify system boundaries for extraction, chunking, vector storage, and LLM calls.
  * Preserve working non-RAG infrastructure (SQLite conversation store, session history, metadata endpoints, frontend layout).
* **Deliverable:** Verified audit map and test execution baseline.

---

### PHASE 1 — Document Ingestion Replacement (Docling)
* **Scope:**
  * Integrate **Docling** as the primary legal document parsing engine.
  * Preserve physical layout, page numbers (1-indexed), tables, and reading order.
  * Preserve legal structural headings, articles, clauses, and annexures.
  * Establish a structured intermediate representation for parsed legal documents.
  * Add parsing regression tests against complex multi-page contracts.
* **Deliverable:** `DoclingParser` service outputting structured legal document representations.

---

### PHASE 2 — Structure-Aware Legal Chunking
* **Scope:**
  * Implement custom legal-aware chunking preserving legal structural integrity:
    * Document title, preamble, and contracting parties
    * Recitals
    * Numbered clauses and subclauses (`Clause 14`, `Clause 21.2(a)`)
    * Annexures and Schedules (`ANNEXURE-I`, `Schedule A`)
    * Definitions block
    * Signatures and execution block
  * Attach rich metadata to each chunk: `document_id`, `chunk_id`, `page_number`, `section_title`, `section_number`, `text`, `document_metadata`.
  * Ensure `ANNEXURE-I` is an independently retrievable chunk unit.
  * Add chunking unit and regression tests verifying clause boundaries.
* **Deliverable:** `StructureAwareLegalChunker` producing rich metadata chunks.

---

### PHASE 3 — Gemini Embeddings + Local Qdrant
* **Scope:**
  * Implement `GeminiEmbeddingProvider` supporting **Gemini Embedding 2** (`text-embedding-004`).
  * Configure environment variable loading (`GEMINI_API_KEY`). Never hardcode secrets.
  * Integrate a local **Qdrant** instance for vector storage.
  * Index structure-aware chunks with full payload metadata into Qdrant.
  * Enforce document namespace isolation to prevent multi-document leakage.
  * Prevent duplicate indexing on repeated uploads (using SHA-256 byte hashes).
  * Implement re-indexing capabilities when embedding configuration changes.
* **Deliverable:** Vector indexing pipeline with Gemini Embedding 2 and local Qdrant.

---

### PHASE 4 — Hybrid Retrieval (Dense + BM25 + RRF)
* **Scope:**
  * Implement lexical **BM25** index over structure-aware chunks.
  * Combine Dense Qdrant retrieval + BM25 keyword retrieval.
  * Implement **Reciprocal Rank Fusion (RRF)**:
    $$RRF(d) = \sum_{m \in \{dense, bm25\}} \frac{1}{60 + r_m(d)}$$
  * Add unit tests verifying retrieval for:
    * Exact legal identifiers (e.g., *"ANNEXURE-I"*, *"Clause 15"*, *"Clause 21"*)
    * Dates, monetary values, and party names
    * Semantic conceptual queries (e.g., *"What is the notice period for termination?"*)
* **Deliverable:** `HybridRetrievalEngine` fusing dense and BM25 candidate lists.

---

### PHASE 5 — Question Routing
* **Scope:**
  * Implement dedicated Question Router distinguishing:
    1. **General Questions:** *"What is the day today?"*, *"What is Python?"*, *"Explain authentication."*
    2. **Document Questions:** *"What is the notice period?"*, *"Who is the tenant?"*, *"What's in ANNEXURE-I?"*
  * Eliminate the defect where *"What is the day today?"* enters retrieval and returns *"Not stated in document"*.
  * General questions bypass document retrieval and route directly to the LLM.
  * Deterministic rule evaluation first to avoid unnecessary classifier LLM tokens.
* **Deliverable:** `QuestionRouter` with unit tests for general vs. document inquiries.

---

### PHASE 6 — Gemini Answer Generation & Grounding
* **Scope:**
  * Implement `GeminiLLMProvider` using **Gemini 3.8 Flash** as the primary answer generator.
  * Inject retrieved evidence enclosed in untrusted machine-readable XML fences (`<context_document_data>`).
  * Enforce strict grounding: answer exclusively from supplied evidence.
  * Implement structured conceptual answer status: `supported`, `partially_supported`, `insufficient_context`.
  * Support partial answers for compound queries without inventing missing facts.
  * Protect against prompt injection embedded within contract texts.
  * Generate and validate claim-level citations with 1-indexed page and section references.
* **Deliverable:** Grounded answer generation module with verified citations.

---

### PHASE 7 — Real-Document Validation Suite
* **Scope:**
  * Validate end-to-end against real commercial contracts, specifically the real **Rental Agreement** that exposed retrieval failures.
  * Execute mandatory test battery:
    1. *"What is this document about?"*
    2. *"Who is the owner?"*
    3. *"Who is the tenant?"*
    4. *"What is the notice period?"*
    5. *"What happens on early termination?"*
    6. *"What's mentioned in ANNEXURE-I?"*
    7. *"What is in this document?"*
    8. *"Which clauses discuss termination?"*
    9. *"What is the security deposit?"*
    10. *"Which page contains ANNEXURE-I?"*
    11. *"Which date is this document issued?"*
    12. *"What is the day today?"*
  * For every test case, inspect and record the full trace:
    $$\text{Question} \to \text{Route} \to \text{Retrieved Chunks} \to \text{Section} \to \text{Page} \to \text{Scores} \to \text{Final Context} \to \text{Answer} \to \text{Citations}$$
  * Verify success by inspecting evidence content, not merely checking for HTTP 200.
* **Deliverable:** Real-document validation report with verified chunk traces.

---

### PHASE 8 — Retrieval & Answer Evaluation Benchmark
* **Scope:**
  * Expand the offline evaluation suite with real failure cases and edge cases.
  * Measure metrics independently across retrieval and generation:
    * Retrieval Recall & Precision
    * Retrieval Relevance
    * Answer Grounding & Correctness
    * Citation Correctness (claim maps to supporting chunk)
    * Refusal Precision (refuses only when truly absent)
    * Latency & Token Usage
  * Never use LLM answer generation alone to assess retrieval quality.
* **Deliverable:** Multi-metric offline evaluation harness.

---

### PHASE 9 — Reranking (DEFERRED)
* **Scope:**
  * Explicitly marked as **DEFERRED**.
  * Revisit local cross-encoder reranking only after the Phase 1–8 hybrid baseline is proven and validated.
  * Reason: Introducing a reranker before proving basic hybrid retrieval adds unnecessary debugging opacity.

---

### PHASE 10 — Production Hardening
* **Scope:**
  * Multi-turn conversational retrieval and entity resolution.
  * Adversarial prompt injection stress tests.
  * Concurrency and SQLite/PostgreSQL connection pooling under load.
  * Production packaging and UI polish.
* **Deliverable:** Production-hardened containerized application.

---

## 3. Acceptance Criteria

The new RAG implementation is considered successful **ONLY** when all of the following conditions are met:

1. **Relevant Evidence Retrieval:** Both dense and lexical retrieval channels surface topically relevant document passages.
2. **ANNEXURE-I Resolution:** Questions targeting *"ANNEXURE-I"* successfully retrieve the annexure section, even if semantic similarity alone is low.
3. **Exact Clause Retrieval:** Inquiries targeting specific clauses (e.g., *"Clause 15"*, *"Clause 21"*) retrieve the exact numbered provisions.
4. **Conceptual Semantic Retrieval:** Conceptual inquiries (e.g., notice period, termination remedies) retrieve relevant clauses regardless of wording variations.
5. **Accurate Question Routing:** General inquiries (*"What is the day today?"*, *"What is Python?"*) do not trigger document retrieval or output false document refusals.
6. **Strict Evidence Grounding:** Answers are factually grounded in retrieved chunks; unsupported facts are not fabricated.
7. **No Unsupported Claims:** The model does not invent terms not present in the contract.
8. **Citation Precision:** Citations correspond directly to verifiable supporting chunks with accurate 1-indexed page and section references.
9. **Document Isolation:** Multi-document environments maintain strict isolation without context bleeding.
10. **API Compatibility:** Existing endpoints (`/api/documents/upload`, `/api/chat`, `/api/conversations`) maintain contract integrity.
11. **Preservation of Working Infrastructure:** Non-RAG components (database persistence, session tracking, frontend layout) are preserved.
