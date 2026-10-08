# Product Requirements Document (PRD)
## Agentic Legal Document Intelligence Application

* **Document Version:** 4.0.0
* **Status:** Functional MVP with a known RAG correctness/reliability gap.
* **Current Priority:** Replace/fix the RAG retrieval core inside the existing application. (Not production-ready for legal retrieval).
* **Author:** Lead Architect & Product Planner
* **Last Updated:** October 8, 2026

---

## 1. Product Overview & Vision

The **Legal Document Intelligence & Q&A Assistant** is an agentic, document-grounded legal intelligence application built on FastAPI and designed for commercial contracts, agreements, and legal documentation (master services agreements, lease agreements, non-disclosure agreements, statements of work, vendor contracts, corporate policies, and terms of service).

### Product Vision
> **An agentic Legal Document Intelligence application that understands legal documents at document, section, clause, and evidence levels; routes user intent; reasons over validated evidence via hybrid semantic + BM25 retrieval; maintains persistent conversation context; detects ambiguity and conflicts; and produces traceable, grounded answers with citations.**

The application continues using the **EXISTING FastAPI application and frontend**. We do **NOT** create a separate RAG project or lab.

### Target End-to-End Pipeline
```text
User Question
      ↓
   FastAPI
      ↓
Question Router
├── General Question ("What is the day today?", "What is Python?")
│      ↓
│   Normal LLM response (Deterministic / Direct LLM, 0 doc retrieval)
│
└── Document Question ("What is the notice period?", "What's in ANNEXURE-I?")
       ↓
Query Preparation
       ↓
Hybrid Retrieval
├── Dense Semantic Retrieval (Gemini Embedding 2 / Qdrant)
└── BM25 Keyword Retrieval
       ↓
Reciprocal Rank Fusion (RRF)
       ↓
Relevant Evidence (Filtered top candidates)
       ↓
Context Builder (<context_document_data> XML enclosure)
       ↓
Gemini LLM (Gemini 3.8 Flash)
       ↓
Citation / Evidence Validation
       ↓
Structured Grounded Answer
```

### Core Operational Principles
1. **The LLM is the reasoning component, not the source of truth:**
   * **PDF Metadata** is the source of truth for document properties (page count, file size, status).
   * **Extracted Document Text & Structural Hierarchy** is the authoritative source of truth for factual evidence.
   * **Hybrid Retrieval (Dense + BM25 via RRF)** provides bounded evidentiary context.
   * **Persisted Conversation Store (SQLite)** maintains historical conversational context.
2. **Deterministic Preference:** If reliable deterministic information is available (e.g., page count, file size, or general chitchat routing), never invoke expensive document retrieval or hallucinate answers.
3. **Auditable Grounding:** Every substantive assertion must map to source evidence with 1-indexed page numbers, section headers, chunk IDs, and text snippets.

---

## 2. Problem Statement & Key Architectural Gaps

Commercial legal agreements are dense, hierarchical, cross-referential instruments containing definitions, operational obligations, conditions precedent, dates, and liability caps.

### Current RAG Reliability Deficiencies:
1. **Vector-Only & Flat Chunking Failure:** Semantic vector search alone is fundamentally insufficient for legal documents. Legal agreements hinge on exact alphanumeric identifiers (*"ANNEXURE-I"*, *"Clause 15"*, *"Clause 21"*, dates, monetary values, party names, defined terms). Dense semantic similarity frequently fails on exact identifiers like *"ANNEXURE-I"*, while pure BM25 lacks semantic generalization for concepts like *"early termination penalties"*.
2. **General Question Misrouting Defect:** Questions unrelated to the document (e.g., *"What is the day today?"*, *"What is Python?"*) are erroneously routed into document retrieval and return false refusals (*"Not stated in document"*). This bug must be eliminated through explicit question routing.
3. **Fragile Ingestion & Chunking:** Fixed-size 500-token/character chunking tears clauses apart, separating sub-clauses from parent articles, recitals, annexures, or definitions, destroying document structure.
4. **Weak Retrieval Grounding & Citation Hallucination:** Previous evaluations (and synthetic benchmarks reporting 100%) masked real-world retrieval failures on complex real documents (such as real Rental Agreements). Retrieved context must be strictly validated before answer synthesis.

---

## 3. Technology Stack & Provider Architecture

### 3.1 Technology Decisions
* **Backend:** FastAPI (Python 3.12).
* **Document Parsing:** **Docling** (replaces legacy PyMuPDF line-by-line parser to produce structured document representation).
* **Chunking:** **Custom Structure-Aware Legal Chunking** (preserving title, parties, recitals, numbered clauses, subclauses, annexures, schedules, definitions, signatures).
* **Embeddings:** **Gemini Embedding 2** as primary embedding provider. Local embedding provider retained as configurable fallback.
* **Vector Database:** **Qdrant** (running locally for development).
* **Keyword Retrieval:** **BM25** (lexical inverted index).
* **Hybrid Retrieval:** **Dense + BM25 fused via Reciprocal Rank Fusion (RRF)**.
* **LLM Provider:** **Gemini 3.8 Flash** as primary answer-generation provider; OpenAI supported through existing provider abstraction.
* **Frontend:** Existing vanilla JS / HTML frontend.
* **Persistence:** Existing SQLite relational repository (`data/legal_qa.db` with WAL mode) preserving conversation, message, citation, and profile schemas.
* **Testing:** Pytest, existing RAG benchmark (expanded with real-document failure cases), API integration tests, and real document smoke tests.

### 3.2 Provider Abstraction
The system utilizes clean provider abstractions. Retrieval architecture is provider-independent:
```text
EmbeddingProvider (Abstract)
├── GeminiEmbeddingProvider (Primary: Gemini Embedding 2)
└── LocalEmbeddingProvider / future fallback

LLMProvider (Abstract)
├── GeminiLLMProvider (Primary: Gemini 3.8 Flash)
├── OpenAILLMProvider (Secondary / Alternative)
└── future providers (e.g., Ollama deferred)
```
* API keys are loaded strictly from environment variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`). **Never hard-code API keys.**
* Gemini and OpenAI do **NOT** have separate RAG pipelines; both consume identical context structures from the retrieval engine.

---

## 4. Question Routing Requirements

The system must deterministically or via lightweight classifier distinguish between:
1. **General Questions:**
   * Examples: *"What is the day today?"*, *"What is Python?"*, *"Explain authentication."*
   * **Behavior:** Directly answered by the LLM without document retrieval or false refusals. The bug where *"What is the day today?"* returns *"Not stated in document"* is explicitly targeted for removal.
2. **Document Questions:**
   * Examples: *"What is the notice period?"*, *"Who is the tenant?"*, *"What's mentioned in ANNEXURE-I?"*, *"What is this document about?"*
   * **Behavior:** Query preparation $\to$ Hybrid Retrieval (Dense + BM25) $\to$ RRF $\to$ Context Building $\to$ Grounded LLM answer.

Deterministic routing rules must be evaluated first to avoid unnecessary LLM calls whenever possible.

---

## 5. Ingestion & Structure-Aware Legal Chunking Requirements

### 5.1 Ingestion Pipeline
```text
Uploaded PDF
     ↓
  Docling
     ↓
Structured Document Representation
     ↓
Structure-Aware Legal Chunking
     ↓
Gemini Embedding 2 + BM25 Index
     ↓
Qdrant (Dense) + Inverted Index (BM25)
```

### 5.2 Legal Structural Units
Chunking must **NOT** be arbitrary fixed-size token slicing. The chunker must identify and preserve:
* Document Title & Header
* Contracting Parties
* Recitals & Preamble
* Numbered Clauses & Subclauses (e.g., `Clause 15`, `Clause 21.2(a)`)
* Annexures & Schedules (e.g., `ANNEXURE-I`, `Schedule A`)
* Definitions Section
* Execution / Signatures block

### 5.3 Chunk Metadata Contract
Every indexed chunk must retain rich metadata:
* `document_id`: Unique identifier of the uploaded document
* `chunk_id`: Deterministic ID (`doc_id_chunk_001`)
* `page_number`: 1-indexed primary page where clause appears
* `section_title`: Section heading (e.g., *"Termination"*, *"Annexure-I - Inventory"*)
* `section_number`: Section/clause identifier (e.g., *"Clause 14"*, *"ANNEXURE-I"*)
* `text`: Cleaned text content of the chunk
* `document_metadata`: Document filename, hash, upload timestamp

---

## 6. Hybrid Retrieval & RRF Specifications

### 6.1 Hybrid Retrieval Design
Vector search alone is insufficient for legal documents. The system must combine:
1. **Dense Semantic Retrieval:** Queries indexed against Gemini Embedding 2 vectors in local Qdrant to capture conceptual similarity (e.g., *"early termination consequences"*).
2. **BM25 Lexical Retrieval:** Token-matched against indexed chunk text to capture exact legal identifiers (e.g., *"ANNEXURE-I"*, *"Clause 21"*, specific dollar amounts, tenant names).

### 6.2 Reciprocal Rank Fusion (RRF)
Rankings from dense search ($R_{dense}$) and BM25 search ($R_{bm25}$) are merged using standard RRF:
$$RRF(d) = \sum_{m \in \{dense, bm25\}} \frac{1}{k + r_m(d)}$$
where $k \approx 60$ and $r_m(d)$ is the 1-indexed rank of chunk $d$ in retrieval method $m$.

### 6.3 Reranking Status
* **DEFERRED:** A dedicated local cross-encoder reranker is deferred until hybrid retrieval (Docling + structure-aware chunks + Gemini embeddings + Qdrant + BM25 + RRF) is proven and verified against real legal documents.

---

## 7. Grounding, Answer Generation & Citations

### 7.1 LLM Generation Guidelines
* Primary LLM: **Gemini 3.8 Flash**.
* Document context is injected within explicit untrusted XML fences (`<context_document_data>`).
* Retrieved document content is strictly treated as untrusted data; prompt injections embedded within legal agreements must never be executed as instructions.
* The model must strictly answer from supplied document evidence.
* It must refuse only when required information is genuinely unavailable.
* Never rely on fragile exact refusal strings like `"Not stated in document"` for application logic.
* Distinguish supported and unsupported portions of compound questions.

### 7.2 Structured Answer Status
Responses must conceptually emit structured confidence states:
* `supported`: Adequate direct evidence found; answer fully grounded.
* `partially_supported`: Some parts answered with evidence; missing parts explicitly noted.
* `insufficient_context`: Document evidence is absent or insufficient to ground the claim.

### 7.3 Citations
* Each claim must map to supporting chunks with page and section references.
* System must never assume every retrieved chunk supports every claim.
* Citation correctness is a mandatory quality gate.

---

## 8. Quality & Acceptance Criteria

The new RAG implementation is successful only when all the following criteria are satisfied:

1. **Relevant Evidence Retrieval:** Relevant document evidence is retrieved across dense and lexical channels.
2. **Exact Identifier Retrieval (ANNEXURE-I):** Questions like *"What is mentioned in ANNEXURE-I?"* retrieve the actual ANNEXURE-I section even if semantic similarity is weak.
3. **Clause-Specific Retrieval:** Clause-specific questions (e.g., *"What does Clause 15 state?"*) retrieve the exact clause.
4. **Conceptual / Semantic Retrieval:** Semantic questions (e.g., *"What is the notice period for termination?"*) retrieve conceptually relevant passages even when phrasing differs.
5. **Accurate Question Routing:** General questions (e.g., *"What is the day today?"*, *"What is Python?"*) do not trigger document retrieval or return false document refusals.
6. **Strict Grounding:** Answers are factually grounded in retrieved evidence; unsupported claims are not hallucinated.
7. **Refusal Precision:** Refusals occur only when the information is genuinely absent.
8. **Citation Correctness:** Citations correspond directly to verifiable supporting chunks with accurate 1-indexed page and section references.
9. **Document Isolation:** Strict namespace isolation prevents context leakage across documents.
10. **API Compatibility:** Existing application APIs (`/api/documents/upload`, `/api/chat`, `/api/conversations`) continue working.
11. **Minimal Disruption:** Existing working non-RAG functionality (conversation persistence, metadata endpoints, frontend layout) is preserved and not rewritten.
