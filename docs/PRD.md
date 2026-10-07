# Product Requirements Document (PRD)
## Agentic Legal Document Intelligence Application

* **Document Version:** 3.0.0
* **Status:** Comprehensive Legal Document Intelligence Specification (Reviewed October 7, 2026)
* **Author:** Lead Architect & Product Planner
* **Last Updated:** October 7, 2026

---

## 1. Product Overview & Vision

The **Legal Document Intelligence & Q&A Assistant** is an agentic, document-grounded legal intelligence application designed for commercial contracts, agreements, and legal documentation (master services agreements, non-disclosure agreements, statements of work, vendor contracts, commercial leases, corporate policies, and terms of service).

### Product Vision
> **An agentic Legal Document Intelligence application that understands legal documents at document, section, clause, and evidence levels; interprets user intent; selects bounded tools; reasons over validated evidence; maintains persistent conversation context; detects ambiguity and conflicts; supports cross-document analysis; and produces traceable, grounded answers with citations.**

The product is explicitly **NOT** merely:
$$\text{RAG} + \text{LLM} + \text{Chatbot}$$

The long-term target architecture is:
$$\text{Document Intelligence} + \text{Bounded Agent} + \text{Tools} + \text{Evidence} + \text{Legal Reasoning} + \text{Persistent Context} + \text{Auditability}$$

### Core Operational Principles
1. **The LLM is the reasoning component, not the source of truth:**
   * **PDF Metadata** is the source of truth for document properties (page count, file size, status).
   * **Extracted Document Text** is the authoritative source of truth for factual evidence.
   * **Structural Section Tree** is the source of truth for section hierarchies and clause numbering (`8.2(b)`).
   * **Validated Retrieval Results** provide bounded evidentiary context.
   * **Persisted Conversation Store** maintains historical conversational context.
2. **Deterministic Preference:** If reliable deterministic information is available, never invoke an LLM to invent or estimate it.
3. **Auditable Grounding:** Every substantive assertion must map to source evidence with 1-indexed page numbers, section headers, chunk IDs, and text snippets.

---

## 2. Problem Statement & Key Architectural Gaps

Commercial legal agreements are dense, hierarchical, cross-referential instruments containing definitions, operational obligations, conditions precedent, dates, and liability caps.

### Gaps in Naive RAG Chatbots:
1. **Semantic Chunk Fallacy:** Top-K semantic chunk retrieval cannot answer document-level questions (*"What is this document about?"*) or structural queries (*"How many pages?"*), returning arbitrary matching snippets or hallucinating chunk counts as page counts.
2. **Volatile Session State:** Client-only chat state (`let chatHistory = []`) vanishes upon browser reload; users cannot maintain multi-turn threads, revisit prior analyses, or link conversations to document versions.
3. **Absence of Legal Structure:** Naive paragraph chunking breaks clause hierarchy (e.g., losing the connection between sub-clause `8.2(b)(ii)` and Article 8).
4. **Ignorance of Cross-References & Defined Terms:** Contracts routinely say *"subject to Section 12.4"* or use defined terms like *"Confidential Information"*; naive search treats these as plain text without resolving definitions or target clauses.
5. **Silent Conflation of Conflicting Clauses:** When contracts contain conflicting terms (e.g., Section 5 says 30 days; Section 12 says 45 days), naive RAG arbitrarily selects one chunk instead of identifying the conflict.
6. **Prompt Injection Vulnerability:** Contracts are untrusted user data; adversarial text inside contracts must never hijack agent instructions.

---

## 3. Product Goals & Core Qualities

### 3.1 Evidence-First Answers
Every factual or legal claim derived from a document must be traceable to:
* Document name and unique ID
* Document content hash / version
* 1-indexed page number
* Section title and clause reference (e.g., `Article 8.2(b)`)
* Bounded evidence snippet ($\le 250$ chars)
* Citation identifier

### 3.2 Whole-Document Understanding
The system understands contracts beyond isolated chunks:
* Document type and governing jurisdiction
* Contracting parties and effective/execution dates
* Defined legal terms and document-specific definitions
* Section and clause hierarchy
* Obligations, rights, conditions, and exceptions
* Cross-references and schedules/appendices

### 3.3 Deterministic Precision
* *"How many pages?"* $\longrightarrow$ PDF metadata (`page_count`) via deterministic tool (**0 LLM tokens**).
* *"What is the filename?"* $\longrightarrow$ Document metadata (`original_filename`) (**0 LLM tokens**).
* *"When was this uploaded?"* $\longrightarrow$ Application metadata (`created_at`) (**0 LLM tokens**).
* *"What is clause 8.2(b)?"* $\longrightarrow$ Structural lookup + exact clause text (**0 LLM tokens**).
* *"What does clause 8.2(b) mean?"* $\longrightarrow$ Evidence retrieval + LLM legal reasoning.

### 3.4 Explicit Uncertainty & Confidence States
The application formally categorizes evidence and confidence states:
* `SUPPORTED`: Adequate direct evidence found; answer fully grounded.
* `PARTIALLY_SUPPORTED`: Some sub-questions supported; missing elements explicitly noted as not found.
* `AMBIGUOUS`: Query permits multiple interpretations; triggers clarification workflow.
* `INSUFFICIENT_EVIDENCE`: Document lacks relevant clauses; triggers deterministic refusal.
* `NOT_FOUND`: Specific clause or term does not exist in the document.
* `CONFLICTING_EVIDENCE`: Multiple clauses provide conflicting terms; system highlights the conflict without picking a winner.
* `CLARIFICATION_REQUIRED`: Query requires disambiguation before execution.

### 3.5 Conflict Detection
When distinct provisions appear contradictory (e.g. 30 days payment in Section 4 vs. 45 days in Section 11):
* The agent identifies and cites both provisions.
* Explains the potential conflict and cross-referencing mechanics.
* Avoids making unauthorized legal determinations about which provision legally prevails.

### 3.6 Legal Hierarchy & Cross-Reference Awareness
* Preserves nested numbering: `Article 8` $\longrightarrow$ `Section 8.2` $\longrightarrow$ `Clause 8.2(b)` $\longrightarrow$ `Sub-clause 8.2(b)(ii)`.
* Detects cross-references (*"subject to Section 12.4"*, *"except as provided in Clause 6"*), fetches the referenced clause, and includes it in reasoning.

### 3.7 Definition Awareness
* Distinguishes ordinary phrases from defined legal terms.
* Identifies document definitions (e.g., *"Confidential Information means..."*) and resolves them when analyzing substantive clauses.

### 3.8 Temporal & Timeline Reasoning
* Identifies effective dates, expiration dates, notice windows, cure periods, and renewal triggers.
* Evaluates temporal logic (e.g., notice required 30 days prior to end of initial 2-year term).

### 3.9 Structured Obligation Extraction
Captures legal commitments in a structured schema:
$$\text{WHO (Party)} \longrightarrow \text{MUST / SHALL (Modality)} \longrightarrow \text{DO WHAT (Action)} \longrightarrow \text{WHEN (Deadline)} \longrightarrow \text{CONDITION} \longrightarrow \text{CONSEQUENCE}$$

### 3.10 Controlled Risk & Exception Analysis
Identifies potentially notable clauses (unusual notice periods, broad indemnities, unilateral termination rights, missing standard clauses) while strictly labeling interpretations as analytical observations, **never as formal legal advice**.

### 3.11 Multi-Document Intelligence & Version Awareness
* Supports single-document, multi-document comparison, and version-to-version amendment tracking.
* Enforces strict namespace isolation to prevent evidence contamination across contracts.

### 3.12 Bounded, Controlled Execution
* Single bounded orchestrator; no unconstrained multi-agent sprawl.
* Strict loop bounds: $\le 2$ iterations for single-doc, $\le 3$ iterations for multi-doc.
* Document text treated strictly as inert untrusted evidence inside `<context_document_data>` XML tags (OPT-016).

---

## 4. Non-Goals & Legal Disclaimers

The product explicitly does **NOT**:
* Provide formal legal advice or substitute for a licensed attorney.
* Predict litigation outcomes or judge statutory validity.
* Perform external legal research across external case law or statutory databases.
* Automatically execute binding contract redlines or author new agreements.

---

## 5. Implementation Status Taxonomy

To maintain absolute clarity, all capabilities are categorized as:
* **CURRENT:** Verified and passing in the existing codebase.
* **IN PROGRESS:** Under active development or partial implementation.
* **PLANNED:** Formally designed target capability scheduled on the roadmap.
* **FUTURE:** Long-term advanced intelligence capability.

### 5.1 Current Implementation Baseline (Verified Oct 7, 2026)
* **PDF Ingestion & Validation [CURRENT]:** Multipart upload, `%PDF` magic bytes, 25 MB file limit, 500 pages, 5,000 chunks, PyMuPDF line-wrap extraction.
* **Duplicate Detection [CURRENT / OPT-001]:** SHA-256 byte hashing detects duplicate uploads and reuses existing indexed documents without redundant embedding.
* **Embeddings & Compatibility [CURRENT / OPT-008]:** FastEmbed (`bge-small-en-v1.5`, 384 dim via ONNX) and TF-IDF (`tfidf-scikit`); index sidecars record dimension and model.
* **Semantic Confidence Gate [CURRENT / OPT-003]:** Dual-threshold gate (`score >= 0.35` with content word match, or `score >= 0.10` with $\ge 35\%$ overlap); bypasses LLM on weak evidence.
* **Compound Query Decomposition [CURRENT / UNANS-005]:** Decomposes compound queries, evaluates sub-questions independently, and synthesizes partial answers without hallucinated citations.
* **Prompt Injection Protection [CURRENT / OPT-016]:** Machine-readable XML delimiters (`<context_document_data>`), instruction priority hierarchy, and adversarial defense.
* **Resource Limits & Telemetry [CURRENT / OPT-017, OPT-021]:** Bounded upload size, pages, chunks, queries (2,000 chars), context (8,000 chars), prompt tokens (4,096); token and cost telemetry.
* **Conversation & Message Relational Store [CURRENT / P0-CHAT-01]:** Durable SQLite relational persistence (`conversations`, `messages`), `/api/conversations` endpoints, stable conversation ID.
* **Document-Scoped Context & Memory Management [CURRENT / P0-CHAT-02]:** Strict multi-document scoping, bounded conversational history ($\le 3$ recent turns), no context leakage across document boundaries.
* **Frontend Multi-Conversation UI & Restoration [CURRENT / P0-CHAT-03]:** Conversation list sidebar, thread switching, active conversation restoration, document selector synchronization.
* **Deterministic Document Metadata Tool [CURRENT / P1-TOOL-01]:** Deterministic PDF metadata retrieval (`page_count`, `original_filename`, `file_size_bytes`, `created_at`, `status`) consuming 0 LLM tokens and 0 retrieval latency.
* **Intent Classification & Multi-Intent Router [CURRENT / P1-ROUT-01]:** Deterministic regex and operational routing across 7 intents (`METADATA`, `DOCUMENT_OVERVIEW`, `STRUCTURE_NAVIGATION`, `EVIDENCE_SEARCH`, `CROSS_SECTION_ANALYSIS`, `MULTI_DOCUMENT_COMPARE`, `UNSUPPORTED`) plus multi-intent subquery splitting.
* **Document Overview & Profile Tool [CURRENT / P1-TOOL-02]:** Caching profile synthesizer returning contract type, parties, effective date, executive summary, and key sections with persistent SQLite backing (`document_profiles`).
* **Evidence Retrieval Tool [CURRENT / P1-TOOL-03]:** Vector and lexical evidence search with namespace isolation, section filtering, and semantic confidence gate integration (OPT-003).
* **Bounded Agent Orchestrator [CURRENT / P1-AGNT-01]:** Bounded agent orchestrator ($\le 2$ iterations for single-doc, $\le 3$ for multi-doc), conversational follow-up contextualization, multi-intent dispatch, grounding and citation verification, and structured `AgentAuditTrace`.
* **Test & Benchmark Baseline [CURRENT]:** 138 passing automated tests (138/138); 16/16 passing offline RAG benchmark cases (100.0%).

---

## 6. Target Agent Architecture & Tool Specifications

### 6.1 Tool Architecture & Classifications

The agent operates through a structured tool registry classified by implementation status:

#### Core Tools
1. **`get_document_metadata` [CURRENT / P1-TOOL-01]:**
   * *Purpose:* Return verified PDF and file metadata (`page_count`, `original_filename`, `file_size_bytes`, `created_at`, `status`).
   * *Type:* Deterministic (0 LLM tokens).
2. **`get_document_profile` [CURRENT / P1-TOOL-02]:**
   * *Purpose:* Return whole-document executive summary, parties, contract type, and key subject areas.
   * *Type:* Pre-computed / cached SQLite store (`document_profiles`).
3. **`search_document_evidence` [CURRENT / P1-TOOL-03]:**
   * *Purpose:* Retrieve grounded chunks passing the `OPT-003` semantic confidence gate with section/page provenance.
   * *Type:* Scoped dense/lexical search.
4. **`get_section_structure` [PLANNED / P2]:**
   * *Purpose:* Navigate table of contents, article hierarchy, and clause boundaries (`8.2(b)`).
   * *Type:* Deterministic AST query (0 LLM tokens).
5. **`compare_document_clauses` [PLANNED / P2]:**
   * *Purpose:* Retrieve and align evidence from two distinct documents for comparison queries with namespace isolation.
   * *Type:* Multi-doc isolated search.

#### Near-Term Tools (Planned P2 / P3)
6. **`resolve_cross_reference` [PLANNED / P2]:**
   * *Purpose:* Identify references like *"subject to Section 12.4"*, fetch referenced clause text, and return combined context.
7. **`lookup_definition` [PLANNED / P2]:**
   * *Purpose:* Retrieve document-specific definitions of defined legal terms.
8. **`extract_obligations` [FUTURE / P3]:**
   * *Purpose:* Extract structured party obligations (Who, What, When, Condition).

---

## 7. Operational Intent Taxonomy

User inquiries are routed across **8 operational intents**:

| Intent | Description | Execution Path | LLM Invocation |
|---|---|---|---|
| `METADATA` | File properties (*"How many pages?"*, *"File size?"*) | `get_document_metadata` | **No (0 Tokens)** |
| `DOCUMENT_OVERVIEW` | Broad inquiries (*"What is this document about?"*) | `get_document_profile` | Profile synthesis if uncached |
| `STRUCTURE_NAVIGATION` | Hierarchy lookups (*"What does Section 8 cover?"*) | `get_section_structure` | **No (0 Tokens)** |
| `EVIDENCE_SEARCH` | Factual/clause questions (*"What is the notice period?"*) | `search_document_evidence` $\to$ Reasoner | Yes (Context synthesis) |
| `CROSS_SECTION_ANALYSIS`| Multi-clause comparisons (*"Before vs after termination"*) | Multi-pass evidence search $\to$ Reasoner | Yes (Comparative reasoning) |
| `MULTI_DOCUMENT_COMPARE`| Comparing contracts (*"Compare Contract A and B"*) | `compare_document_clauses` $\to$ Reasoner | Yes (Comparative reasoning) |
| `CLARIFICATION_REQUIRED`| Ambiguous queries (*"What about notice?"*) | Clarification prompt to user | Yes (Lean prompt) |
| `UNSUPPORTED` | Out-of-domain or unanswerable queries | Deterministic refusal gate | **No (0 Tokens)** |

---

## 8. User-Visible Transparency & Auditability

To provide enterprise legal trust without exposing raw chain-of-thought, assistant responses include structured **Execution Transparency Metadata**:
```json
{
  "detected_intent": "EVIDENCE_SEARCH",
  "tools_used": ["search_document_evidence"],
  "documents_consulted": ["master_services_agreement.pdf (v1)"],
  "evidence_state": "SUPPORTED",
  "validation_status": {
    "grounding_passed": true,
    "citations_verified": true,
    "conflict_detected": false
  },
  "sources": [
    {
      "document_name": "master_services_agreement.pdf",
      "page_number": 7,
      "section": "Article 8.2(b) Termination Notice",
      "snippet": "Either party may terminate upon thirty (30) days prior written notice..."
    }
  ]
}
```

---

## 9. Quality, Safety & Acceptance Criteria

| ID | Quality | Given | When | Then |
|---|---|---|---|---|
| **AC-AG-01** | **Deterministic Metadata** | An indexed agreement | User asks *"How many pages does this document have?"* | System invokes `get_document_metadata` and returns the exact PDF page count with 0 LLM tokens. |
| **AC-AG-02** | **Document Overview** | An indexed agreement | User asks *"What is this document about?"* | System invokes `get_document_profile` and returns a grounded overview of agreement scope, parties, and type. |
| **AC-AG-03** | **Conflict Detection** | Agreement with 30-day notice in Sec 4 and 45-day notice in Sec 11 | User asks *"What is the notice period?"* | System identifies both provisions, explains the potential conflict, cites both sections, and avoids picking a winner. |
| **AC-AG-04** | **Cross-Reference Resolution**| Clause states *"subject to Section 12.4"* | User asks for clause terms | System retrieves both the primary clause and Section 12.4, citing both. |
| **AC-AG-05** | **Multi-Doc Comparison** | Two uploaded agreements | User asks *"Compare termination in Contract A and B"* | System searches each document independently and produces a side-by-side comparison with tagged citations. |
| **AC-AG-06** | **Clarification Workflow** | Agreement has termination, payment, and SLA notice | User asks *"What is the notice rule?"* | System responds with intent `CLARIFICATION_REQUIRED`, asking which notice type the user intends. |
| **AC-AG-07** | **Chat Persistence** | Active conversation with multiple turns | User refreshes the browser | Frontend restores full message history, citations, and document context from `/api/conversations/{id}`. |
| **AC-AG-08** | **Prompt Injection Resistance** | Adversarial prompt embedded in contract text | User queries contract | Document text is treated strictly as inert data inside `<context_document_data>` XML tags; system directives are never breached. |
