# ARCHITECTURE BASELINE — LEGAL QA INTELLIGENCE UPGRADE (PHASE 0 AUDIT)

**Date**: 2026-10-08  
**Repository**: Legal QA chatbot  
**Author**: Lead Software Architect / AI Engineer / Legal Document Intelligence Engineer  

---

## 1. Executive Summary & Existing Architecture

The application is a full-stack Legal Document Q&A Assistant featuring a FastAPI backend, a vanilla JS modern frontend with responsive layouts, document modal viewers, and an SQLite-backed metadata and conversation repository.

### Component Overview:
* **API Framework**: FastAPI (`app/main.py`, `app/api/routes_*.py`).
* **Storage / Database**: SQLite with WAL mode (`data/legal_qa.db`), managed via `sqlite3` in [repository.py](file:///home/rails/Work/Legal%20QA%20chatbot/app/persistence/repository.py). Document metadata is also indexed in `data/uploads/documents_meta.json`.
* **Vector Store & Indexing**: In-memory numpy cosine similarity store with on-disk `.npy` and `_chunks.json` serialization (`app/services/vector_store.py`). Supports pluggable embeddings (TF-IDF local default, Gemini dense embeddings).
* **Document Parsing**: PyMuPDF (`fitz` / `pymupdf`) for PDFs and RapidOCR (`rapidocr_onnxruntime`) for scanned images. Structure parser identifies hierarchical Articles, Sections, Clauses, Definitions, and Cross-references.
* **Agent / Orchestrator**: `AgentOrchestrator` (`app/services/agent_orchestrator.py`) coordinating 7 operational intents, deterministic tools (Metadata, Profile, Navigation), bounded evidence retrieval, and grounded answer synthesis.
* **Citation & Evidence Handling**: `CitationService` and `CitationValidator` ensuring claims link back to document chunks with page and section numbers.

---

## 2. Existing Data Flow

```text
User Question + Document ID + Conversation ID
                  ↓
          [routes_chat.py]
  - Query length & Top-K hard limits check
  - Document existence & isolation validation
  - Conversation persistence & bounded history retrieval
                  ↓
        [AgentOrchestrator]
  - Bounded conversational contextualization (_contextualize_query)
  - Intent classification (IntentRouter)
                  ↓
       [Execution Branch]
  ├── Deterministic Metadata Tool (0 LLM tokens)
  ├── Document Profile / Overview Tool
  ├── Section Structure Navigation Tool
  └── Substantive Evidence Search
            ↓
    [RetrievalService]
  - Query embedding (TF-IDF / Dense)
  - Broad candidate search (top_k * 4, min 20)
  - Semantic relevance confidence gate
  - Reranker (clause/section identifier boost + content overlap)
  - Context deduplication (nested substring suppression)
            ↓
   [Answer Generation]
  - Grounded answer synthesis (Mock / Gemini LLM)
  - Conflict detection, Temporal reasoner, Obligation extraction
  - Citation validation & grounding check
            ↓
   [Response & Telemetry]
  - Latency, token usage, and citation recording
  - Conversation persistence in SQLite
```

---

## 3. Existing Retrieval Pipeline

* **Lexical / Semantic**: Currently relies on TF-IDF cosine similarity or dense vectors (`EmbeddingService` + `VectorStore`).
* **Semantic Relevance Gate**: `is_context_relevant()` in [retrieval_service.py](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/retrieval_service.py) strips stopwords and checks overlap against top retrieved chunk score.
* **Reranking**: Candidate scoring boosts matches with section/clause references (`+0.25`) and content word overlap (`+0.15`).
* **Deduplication**: Subsumed/overlapping chunks (>85% character match) are pruned.

---

## 4. Existing Conversation Pipeline & Root Cause of Follow-up Failure

### Reproduction & Investigation:
The required regression sequence was evaluated:
1. **Q1**: *"What is the notice period for early termination?"*
2. **Q2**: *"Who can initiate it?"*
3. **Q3**: *"What happens to indemnification obligations after that occurs?"*

### Root Cause Analysis:
1. **Pronoun & Event Resolution Gap**:
   * Previously, `_contextualize_query` in `AgentOrchestrator` only checked generic cues like `"previous clause"` or `"what about it"`. When given `"Who can initiate it?"` or `"after that occurs"`, the query remained ungrounded or was naively appended with previous text.
   * Furthermore, `RetrievalService.extract_content_words()` did not treat event verbs like `"occurs"` / `"happens"` as stopwords, causing the semantic relevance gate to penalize queries where those words had no exact match in the target chunk.
   * Recent commit `f186317` added initial pattern-based pronoun replacement and added `"occurs"`, `"happens"` to `STOPWORDS`.
2. **Remaining Weaknesses in Conversation Context**:
   * Currently, context is extracted only from the immediately preceding turn (`last_user_turn` and `last_assistant_turn`). Multi-hop threads spanning 3+ turns lack a unified **Structured Conversation State** (e.g. `active_topic`, `active_clause`, `active_entities`, `active_parties`).
   * Pronoun resolution is pattern/regex based rather than semantic/entity-aware. If the question uses an unhandled phrasal variation (e.g. `"Can they assign them?"` or `"Does this liability continue?"`), the query falls back to elliptical appending rather than semantic slot filling.

---

## 5. Existing Document Intelligence & Legal Reasoning

* **Structure Parser**: Regex-based extraction of `Article`, `Section`, `Clause`, `LegalDefinition`, and `CrossReference`.
* **Legal Reasoning Modules**:
  * `ConflictDetector`: Identifies numeric discrepancies in notice periods and cure windows across sections.
  * `TemporalReasoner`: Extracts deadlines, cure periods, and relative timeline facts.
  * `ObligationExtractor`: Identifies `Party -> Modality -> Action -> Deadline`.
  * `RiskAnalyzer`: Identifies one-sided termination and uncapped liabilities.

---

## 6. Existing Test Coverage & Benchmark Results

* **Pytest Suite**: **188 passed**, 0 failed (12.97s).
* **Legal QA Benchmark Suite (OPT-018)**: **31/31 passed (100%)**.
  * Categories tested: `direct_fact`, `multi_clause`, `unanswerable`, `adversarial`, `citation`, `retrieval`, `defined_term`, `structure_nav`, `obligations`, `risk_analysis`.
  * Latency averages: Retrieval = 1.04ms, Embedding = 0.00ms, LLM = 0.10ms, Total = 1.49ms.

---

## 7. Known Weaknesses & Improvement Opportunities

1. **Conversation State**: Lacks persistent structured dialogue state tracking (`ConversationState`: topic, entities, active clause, definitions in play).
2. **Reference Resolution**: Uses regex rules; should integrate semantic slot-filling using extracted legal entities and defined terms.
3. **Retrieval**: Currently TF-IDF + cosine or dense-only; lacks true hybrid BM25 + dense fusion (e.g., Reciprocal Rank Fusion / linear score fusion) with structural weighting.
4. **Agent Query Planning**: Query planning is heuristic; lacks explicit sub-question planning for compound multi-hop queries that require synthesizing distinct sections (e.g., termination + survival + indemnification).

---

## 8. Proposed Phase 1 Implementation Plan: Conversation Intelligence

### Objective:
Upgrade conversation intelligence to robustly maintain conversation context, resolve complex legal references, pronouns, and follow-ups across arbitrary turns without brittle regexes breaking.

### Planned Changes:
1. **Structured Conversation State**:
   * Add a structured representation model (`ConversationContextState`) tracking: `active_document`, `active_topic`, `active_clause`, `active_parties`, `active_entities`, `last_resolved_query`.
   * Update `ConversationService` / `AgentOrchestrator` to update and consult this state across multi-turn interactions.
2. **Semantic Reference & Entity Resolver**:
   * Expand reference resolution to leverage entities and defined terms from the active document profile and conversation history.
   * Resolve pronouns (`it`, `that`, `this`, `they`, `them`, `those`, `the provision`, `the obligation`, `the termination`, `the above section`).
3. **Automated Multi-turn Regression Tests**:
   * Add dedicated unit tests for the exact 3-turn sequence specified in prompt:
     - Q1: *What is the notice period for early termination?*
     - Q2: *Who can initiate it?*
     - Q3: *What happens to indemnification obligations after that occurs?*
   * Add edge cases (cross-turn pronoun shifts, party resolution, obligations continuation).

### Files Expected to Change:
* `app/models/conversation.py` / `app/models/agent.py` (Structured state models)
* `app/services/agent_orchestrator.py` (Conversation state tracking & reference resolution)
* `app/services/conversation_service.py` (State persistence integration)
* `tests/unit/test_conversation_context.py` (Extended multi-turn regression suite)

### Dependencies Required:
* **None**. Everything will be cleanly implemented using the existing Python 3.12 stack, Pydantic, and existing NLP/regex utilities.
