# Development Plan & Implementation Roadmap
## Agentic Legal Document Intelligence Application

* **Document Version:** 3.0.0
* **Status:** Grounded Agentic Implementation Roadmap (Reviewed October 7, 2026)
* **Author:** Lead Architect & QA Engineering Lead
* **Last Updated:** October 7, 2026

---

## 1. Roadmap Architecture & Engineering Principles

This roadmap organizes the development of the **Legal Document Intelligence Application** into strict dependency phases:

1. **Never build an agent before its tools exist:** Implementing agent loops without deterministic metadata or retrieval tools leads to mocked abstractions and architectural churn.
2. **Persistence First (P0):** Establishing durable conversation and document state in SQLite is the necessary foundation for session tracking, multi-turn history, and frontend resilience.
3. **Preserve Completed Baselines:** 93 automated unit/integration tests and 16/16 RAG evaluation benchmark cases are passing and must remain green across all milestones.
4. **Lean & Bounded Agent Execution:** The agent loop is constrained ($\le 2$ iterations for single-doc, $\le 3$ for multi-doc) to guarantee deterministic latency and cost bounds.

---

## 2. Capability Catalog & Classification

| Task ID | Component / Capability | Horizon | Role in Agentic Architecture |
|---|---|---|---|
| **OPT-001** | Duplicate Document Detection | **CURRENT** | Content-based duplicate detection using SHA-256 byte hashing. |
| **OPT-003** | No-Evidence = No-LLM Gate | **CURRENT** | Serves as evidentiary validation gate inside `search_document_evidence`. |
| **UNANS-005**| Compound Query Decomposition | **CURRENT** | Baseline for multi-part query splitting and partial answerability. |
| **OPT-008** | Dense Local Embeddings | **CURRENT** | FastEmbed ONNX local dense vectors backing the evidence tool. |
| **OPT-016** | Prompt Injection Defense | **CURRENT** | XML evidentiary delimitation (`<context_document_data>`) and instruction hierarchy. |
| **OPT-017** | Token & Cost Telemetry | **CURRENT** | Request latency, token accounting, and cost tracking. |
| **OPT-018** | RAG Evaluation Benchmark | **CURRENT** | 16/16 offline evaluation cases; expanded into Agentic Evaluation Suite. |
| **OPT-021** | Hard Resource Limits | **CURRENT** | Bounded file size, pages, chunks, queries, and prompt tokens. |
| **P0-CHAT-01**| Conversation & Message Persistence | **COMPLETED** | SQLite relational persistence for conversations, messages, citations, and telemetry. |
| **P0-CHAT-02**| Document-Scoped Context & Memory | **COMPLETED** | Bounded sliding window (`MAX_HISTORY_TURNS = 3`) and document context association. |
| **P0-CHAT-03**| Frontend Conversation State Restore | **COMPLETED** | Sidebar conversation list and state restoration on page refresh. |
| **P1-TOOL-01**| Document Metadata Tool | **COMPLETED** | Deterministic resolution of page counts, filenames, sizes with 0 LLM tokens. |
| **P1-ROUT-01**| Intent Classification & Router | **COMPLETED** | Hybrid router classifying 7 operational intents with multi-intent decomposition. |
| **P1-TOOL-02**| Document Overview & Profile Tool | **COMPLETED** | Pre-computed or cached whole-document executive summary and parties in SQLite. |
| **P1-TOOL-03**| Evidence Retrieval Tool | **COMPLETED** | Discrete tool wrapping vector search and OPT-003 confidence gate. |
| **P1-AGNT-01**| Agent Orchestrator & Bounded Loop | **COMPLETED** | Coordinates tool execution, manages bounded iterations, and synthesizes answers. |
| **P1-EVAL-01**| Agentic Evaluation Suite | **COMPLETED** | 138 unit tests and 16/16 offline RAG benchmark cases passing deterministically. |
| **P2-DOC-01** | Section Tree & Structural AST | **COMPLETED** | Structural hierarchy parsing (`8` $\to$ `8.2` $\to$ `8.2(b)`), definitions, and cross-references. |
| **P2-TOOL-04**| Section & Structure Tool | **COMPLETED** | Clause lookups and table-of-contents navigation (0 LLM tokens). |
| **P2-TOOL-05**| Cross-Reference & Definition Tools | **COMPLETED** | Resolves *"subject to Section 12.4"* and defined legal terms. |
| **P2-MDOC-01**| Multi-Document Comparison Tool | **COMPLETED** | Cross-contract clause alignment with isolated document namespaces. |
| **OPT-006**  | Query Contextualization Engine | **COMPLETED** | Follow-up pronoun rewriter using bounded conversation history. |
| **P3-REAS-01**| Conflict & Temporal Reasoner | **COMPLETED** | Detects conflicting provisions and reasons across contract timelines. |
| **P3-OBLE-01**| Obligation Extraction Tool | **COMPLETED** | Extracts structured commitments (Who $\to$ What $\to$ When $\to$ Condition). |
| **P3-RISK**   | Analytical Risk & Exception Analysis| **COMPLETED** | Identifies uncapped liability, one-sided termination, and unusual notice terms. |
| **P3-RETRIEVAL**| Context Deduplication & Fusion | **COMPLETED** | Subsumed chunk deduplication and token pruning while preserving score. |
| **DB-001**   | PostgreSQL Adapter | **COMPLETED** | Configurable `DATABASE_URL` with pooled connection management. |
| **DOC-001**  | Selective OCR Pipeline | **COMPLETED** | Selective OCR fallback hook for low-text pages. |
| **PROD-001** | Production Containerization | **COMPLETED** | Multi-stage Docker packaging (`Dockerfile`, `.dockerignore`). |

---

## 3. Phased Roadmap Specifications

### Milestone P0: Foundation & Persistence (MUST HAVE) — COMPLETED
* **P0-CHAT-01:** Durable SQLite relational store for conversations, messages, citations, and telemetry.
* **P0-CHAT-02:** Document-scoped context and bounded sliding memory ($\le 3$ turns).
* **P0-CHAT-03:** Multi-conversation frontend sidebar and state restoration on page reload.

### Milestone P1: Agentic Core & Tool Orchestration (MUST HAVE) — COMPLETED
* **P1-TOOL-01:** Deterministic metadata resolution (0 LLM tokens).
* **P1-ROUT-01:** Intent classification across 7 intents with multi-intent decomposition.
* **P1-TOOL-02:** Whole-document profile synthesis and SQLite caching.
* **P1-TOOL-03:** Scoped evidence retrieval with semantic confidence gate.
* **P1-AGNT-01:** Bounded agent orchestrator with loop bounds and citation verification.
* **P1-EVAL-01:** Full automated test suite and offline RAG evaluation benchmark.

### Milestone P2: Document Intelligence & Legal Hierarchy — COMPLETED
* **P2-DOC-01 (Section Tree & Structural AST):** Implemented `StructureParser` parsing Articles, Sections, Clauses, sub-clauses, page ranges, defined terms, and internal cross-references.
* **P2-TOOL-04 (Section & Structure Tool):** Implemented `SectionStructureTool` for deterministic table of contents and clause navigation consuming 0 LLM tokens.
* **P2-TOOL-05 & P2-TOOL-05B (Cross-Reference & Definition Tools):** Implemented `CrossReferenceTool` and `DefinitionTool` resolving internal cross-references within isolated document scopes and distinguishing defined legal terms from ordinary phrasing.
* **P2-MDOC-01 (Multi-Document Comparison Tool):** Implemented `MultiDocumentComparisonTool` performing isolated searches across document pairs with status classifications (`same`, `different`, `present_only_in_a`, `present_only_in_b`, `insufficient_evidence`).
* **OPT-006 (Contextual Follow-up Engine):** Bounded pronoun resolution and antecedent linking preserving document isolation.

### Milestone P3: Legal Reasoning & Advanced Retrieval — COMPLETED
* **P3-REAS-01 (Conflict Detection):** Implemented `ConflictDetector` discovering numerical and temporal inconsistencies across provisions without choosing a controlling clause.
* **P3-TEMPORAL (Timeline Reasoning):** Implemented `TemporalReasoner` extracting structured deadlines, notice windows, and cure periods.
* **P3-OBLE-01 (Obligation Extraction):** Implemented `ObligationExtractor` structuring modalities (`shall`, `must`, `may not`, `may`), parties, actions, and conditions.
* **P3-RISK (Controlled Risk & Exception Analysis):** Implemented `RiskAnalyzer` providing analytical observations on uncapped liabilities and one-sided clauses.
* **P3-RETRIEVAL (Context Deduplication):** Implemented `deduplicate_chunks` in `RetrievalService` pruning duplicate or subsumed text chunks.

### Milestone P4: Enterprise Production Readiness — COMPLETED
* **P4-DB (PostgreSQL Readiness):** Added `DATABASE_URL` configuration and engine pooling in `DatabaseManager` supporting both SQLite development and production PostgreSQL.
* **P4-DOC (Selective OCR):** Added `_attempt_selective_ocr` hook in `PDFService` targeting pages below minimum text thresholds.
* **P4-PROD (Production Docker):** Added multi-stage `Dockerfile` (non-root runner, health checks) and `.dockerignore`.
* **Frontend Transparency Pass:** Rendered transparent tool badges, uncertainty indicators, and persistent conversation selectors in UI.
