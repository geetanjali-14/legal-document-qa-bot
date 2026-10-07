# Technical Architecture Document
## Agentic Legal Document Intelligence Application

* **Document Version:** 3.0.0
* **Status:** Grounded Agentic System Architecture & Document Intelligence Pipeline (Reviewed October 7, 2026)
* **Author:** Lead Architect & Systems Engineering Team
* **Last Updated:** October 7, 2026

---

## 1. System Architecture Overview

The **Legal Document Intelligence Application** architecture is designed around the core principle:
> **The LLM is the reasoning component, not the source of truth.**

```text
                                  USER QUERY + CONVERSATION ID + ACTIVE DOC(S)
                                                        │
                                                        ▼
                                ┌──────────────────────────────────────────────┐
                                │ Conversation & Context Manager               │
                                │ - Restores session from SQLite               │
                                │ - Bounded history (MAX 3 turns, no snippets) │
                                │ - Resolves active document(s) & version scope│
                                └───────────────────────┬──────────────────────┘
                                                        │
                                                        ▼
                                ┌──────────────────────────────────────────────┐
                                │ Intent Classifier & Multi-Intent Router      │
                                │ - Deterministic regex rules (0 Tokens)       │
                                │ - Lightweight classifier prompt fallback     │
                                │ - Ambiguity detection -> CLARIFICATION       │
                                └───────────────────────┬──────────────────────┘
                                                        │
         ┌───────────────────────┬──────────────────────┼──────────────────────┬──────────────────────┐
         ▼                       ▼                      ▼                      ▼                      ▼
┌──────────────────┐    ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ METADATA         │    │ DOC_OVERVIEW     │   │ STRUCTURE / REF  │   │ EVIDENCE_SEARCH  │   │ MULTI_DOC_COMPARE│
│ get_metadata     │    │ get_doc_profile  │   │ get_structure    │   │ search_evidence  │   │ compare_clauses  │
│ (0 LLM Tokens)   │    │ (Profile/TOC)    │   │ resolve_ref (AST)│   │ (Gate + Reasoner)│   │ (Isolated scopes)│
└────────┬─────────┘    └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
         │                       │                      │                      │                      │
         └───────────────────────┼──────────────────────┴──────────────────────┼──────────────────────┘
                                 │
                                 ▼
                                ┌──────────────────────────────────────────────┐
                                │ Agent Orchestrator & Legal Reasoner          │
                                │ - Bounded iterations (Single-doc: 2, Multi: 3)│
                                │ - Evidence validation & Conflict Detection   │
                                │ - Fences evidence in <context_document_data> │
                                └───────────────────────┬──────────────────────┘
                                                        │
                                                        ▼
                                ┌──────────────────────────────────────────────┐
                                │ Grounding & Citation Validation Engine       │
                                │ - Claim-level evidence verification          │
                                │ - Verifies 1-indexed page & section mapping  │
                                │ - Clears citations if output is a refusal    │
                                └───────────────────────┬──────────────────────┘
                                                        │
                                                        ▼
                                ┌──────────────────────────────────────────────┐
                                │ Conversation Persistence & Audit Repository  │
                                │ - Commits messages, citations, telemetry     │
                                │ - Execution transparency audit record        │
                                │ - SQLite repository (data/legal_qa.db)       │
                                └───────────────────────┬──────────────────────┘
                                                        │
                                                        ▼
                        GROUNDED ANSWER + VERIFIED CITATIONS + TRANSPARENCY AUDIT
```

---

## 2. Document Intelligence Ingestion Pipeline

Ingestion transitions from a flat chunker to a multi-stage **Document Intelligence Pipeline**:

```text
Upload PDF Binary Stream
            │
            ▼
┌───────────────────────────────────────┐
│ 1. Document Validation & Hashing      │  [SYNCHRONOUS / DETERMINISTIC]
│ - Magic bytes (%PDF), 25 MB limit     │
│ - SHA-256 byte hashing (OPT-001)      │
└───────────────────┬───────────────────┘
                    │ Unseen Hash
                    ▼
┌───────────────────────────────────────┐
│ 2. Text Extraction & Page Preservation│  [SYNCHRONOUS / DETERMINISTIC]
│ - PyMuPDF block extraction            │
│ - Line-wrap hyphen reconstruction     │
│ - 500-page limit check                │
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│ 3. Structural Section & Clause Parser │  [SYNCHRONOUS / DETERMINISTIC]
│ - Detects Article/Section hierarchy   │
│ - Extracts nested numbering (8.2(b))  │
│ - Identifies Defined Terms table      │
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│ 4. Semantic Chunking & Vectors        │  [SYNCHRONOUS / DETERMINISTIC]
│ - Chunks inherit Section & Page tags  │
│ - FastEmbed BGE-Small dense vectors   │
│ - Sidecar metadata (OPT-008)          │
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│ 5. Document Profile Synthesizer       │  [ASYNCHRONOUS / CACHED LLM]
│ - Executive summary & key topics      │
│ - Identified parties & effective date │
│ - Persisted to SQLite document_profiles│
└───────────────────────────────────────┘
```

---

## 3. Tool Architecture & Registry

Tools are decoupled interfaces adhering to a strict abstract contract:

### Core Tools (P0 / P1)
1. **`get_document_metadata` [CURRENT / P1-TOOL-01]:**
   * *Signature:* `(document_id: str) -> MetadataResult`
   * *Returns:* `page_count`, `original_filename`, `file_size_bytes`, `created_at`, `status`. (0 LLM tokens).
2. **`get_document_profile` [CURRENT / P1-TOOL-02]:**
   * *Signature:* `(document_id: str) -> ProfileResult`
   * *Returns:* `document_type`, `parties`, `effective_date`, `executive_summary`, `major_sections`. Caches in SQLite `document_profiles`.
3. **`search_document_evidence` [CURRENT / P1-TOOL-03]:**
   * *Signature:* `(document_ids: List[str], query: str, top_k: int = 4) -> EvidenceResult`
   * *Returns:* Chunks passing `OPT-003` confidence gate with page/section citations.
4. **`get_section_structure` [PLANNED / P2]:**
   * *Signature:* `(document_id: str, section_number: Optional[str]) -> StructureResult`
   * *Returns:* Table of contents, clause hierarchy, page numbers. (0 LLM tokens).

### Near-Term Tools (P2)
5. **`resolve_cross_reference`:**
   * *Signature:* `(document_id: str, target_section: str) -> ReferenceResult`
   * *Returns:* Exact text of referenced provision (e.g., Section 12.4).
6. **`lookup_definition`:**
   * *Signature:* `(document_id: str, term: str) -> DefinitionResult`
   * *Returns:* Defined meaning from contract's Definitions section.
7. **`compare_document_clauses`:**
   * *Signature:* `(doc_a_id: str, doc_b_id: str, topic: str) -> ComparisonResult`
   * *Returns:* Isolated, side-by-side evidence chunks tagged by document ID.

---

## 4. Conflict Detection & Legal Reasoning Architecture

### Conflict Detection Engine
When a query touches provisions that appear contradictory:
1. `search_document_evidence` gathers candidate chunks from all relevant sections.
2. The Legal Reasoner detects disparate values (e.g., notice period: 30 days vs. 45 days).
3. The Reasoner marks state as `CONFLICTING_EVIDENCE`.
4. Output format:
   > *"The document contains potentially conflicting provisions regarding notice:*
   > *1. Section 4.2 (Page 3) specifies 30 days notice.*
   > *2. Section 11.1 (Page 8) specifies 45 days notice.*
   > *Note: Whether one provision takes legal precedence depends on contractual interpretation rules; no automated determination is made."*

---

## 5. Persistence & Audit Schema (SQLite)

```sql
CREATE TABLE conversations (
    conversation_id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    document_ids JSON NOT NULL, -- List of active document IDs
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(32) DEFAULT 'active'
);

CREATE TABLE messages (
    message_id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL, -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    intent VARCHAR(32),
    evidence_state VARCHAR(32), -- 'SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONFLICTING', etc.
    sources JSON, -- Serialized List[Citation]
    telemetry JSON, -- Serialized ChatTelemetry
    transparency_audit JSON, -- Detected intent, tools used, validation checks
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE document_profiles (
    document_id VARCHAR(36) PRIMARY KEY,
    content_hash VARCHAR(64) NOT NULL,
    document_type VARCHAR(128),
    parties JSON,
    effective_date VARCHAR(64),
    executive_summary TEXT,
    major_sections JSON,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);
```

---

## 6. Architectural Risks & Mitigations

| Risk | Description | Concrete Architectural Mitigation |
|---|---|---|
| **Over-Agentification** | Autonomous loop latency spikes and runaway token spend. | Bounded execution loop ($\le 2$ iterations for single-doc); deterministic routing of metadata queries with 0 tokens. |
| **Hallucinated Summaries** | Precomputed summaries invent contract terms. | Summaries are synthesized exclusively from extracted text chunks; profile stores source page breadcrumbs. |
| **Silent Conflict Selection** | Model picks one provision when two conflict. | Conflict detection engine scans for numerical/temporal disparities across retrieved chunks and flags `CONFLICTING_EVIDENCE`. |
| **Cross-Document Contamination** | Searching across Document A and B mixes clauses. | Isolated retrieval namespaces per document; citations explicitly tag source `document_id`. |
| **Prompt Injection Hijack** | Malicious text inside contracts commands the agent. | XML boundaries (`<context_document_data>`) per OPT-016; system prompt instruction hierarchy. |
| **SQLite Concurrency** | Database locking on concurrent writes. | Scoped sessions, WAL mode enabled; repository abstraction supports future PostgreSQL migration if needed. |
