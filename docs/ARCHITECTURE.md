# Technical Architecture Document
## Agentic Legal Document Intelligence Application

* **Document Version:** 4.0.0
* **Status:** Functional MVP with known RAG correctness gap; Target RAG Architecture Document.
* **Current Priority:** Implement Hybrid RAG Core (Docling + Structural Chunker + Gemini Embedding 2 + Local Qdrant + BM25 + RRF + Question Routing + Gemini 3.8 Flash).
* **Author:** Lead Architect & Systems Engineering Team
* **Last Updated:** October 8, 2026

---

## 1. System Architecture Overview

The **Legal Document Intelligence Application** architecture is built on the EXISTING FastAPI backend and vanilla JavaScript frontend. We do **NOT** create a separate RAG project or lab.

```text
                                  USER QUERY + CONVERSATION ID + ACTIVE DOC(S)
                                                        │
                                                        ▼
                                ┌──────────────────────────────────────────────┐
                                │ FastAPI API Gateway (routes_chat.py)         │
                                │ - Request validation, rate & resource limits │
                                │ - Resolves active document(s) & conversation │
                                └───────────────────────┬──────────────────────┘
                                                        │
                                                        ▼
                                ┌──────────────────────────────────────────────┐
                                │ Question Router                              │
                                │ - Deterministic rules & lightweight classifier│
                                └──────────────┬───────────────────────────────┘
                                               │
               ┌───────────────────────────────┴───────────────────────────────┐
               ▼                                                               ▼
    ┌───────────────────────────────┐                       ┌──────────────────────────────────────────────┐
    │ General Question Path         │                       │ Document Question Path                       │
    │ - "What is the day today?"    │                       │ - "What is the notice period?"               │
    │ - "What is Python?"           │                       │ - "What is mentioned in ANNEXURE-I?"         │
    │                               │                       │ - "Who is the tenant?"                       │
    │ Direct LLM (0 doc retrieval)  │                       └──────────────────────┬───────────────────────┘
    │ Avoids false refusal bug      │                                              │
    └──────────────┬────────────────┘                                              ▼
                   │                                        ┌──────────────────────────────────────────────┐
                   │                                        │ Query Preparation & Expansion                │
                   │                                        │ - Term extraction & clause normalization     │
                   │                                        └──────────────────────┬───────────────────────┘
                   │                                                               │
                   │                                                               ▼
                   │                                        ┌──────────────────────────────────────────────┐
                   │                                        │ Hybrid Retrieval Engine                      │
                   │                                        │ ┌──────────────────────┐ ┌──────────────────┐│
                   │                                        │ │ Dense Semantic Search│ │ BM25 Lexical     ││
                   │                                        │ │ Gemini Embedding 2   │ │ Inverted Index   ││
                   │                                        │ │ Local Qdrant Store   │ │ Keyword Matching ││
                   │                                        │ └──────────┬───────────┘ └────────┬─────────┘│
                   │                                        │            └──────────┬───────────┘          │
                   │                                        │                       ▼                      │
                   │                                        │ Reciprocal Rank Fusion (RRF, k=60)           │
                   │                                        └──────────────────────┬───────────────────────┘
                   │                                                               │
                   │                                                               ▼
                   │                                        ┌──────────────────────────────────────────────┐
                   │                                        │ Context Builder                              │
                   │                                        │ - Untrusted XML fencing                      │
                   │                                        │   (<context_document_data>)                  │
                   │                                        │ - Metadata preservation (pages, clauses)     │
                   │                                        └──────────────────────┬───────────────────────┘
                   │                                                               │
                   │                                                               ▼
                   │                                        ┌──────────────────────────────────────────────┐
                   │                                        │ Answer Generator (Gemini 3.8 Flash)          │
                   │                                        │ - Strict evidence grounding                  │
                   │                                        │ - Structured status (supported / partial)    │
                   │                                        │ - Never treats doc text as instructions      │
                   │                                        └──────────────────────┬───────────────────────┘
                   │                                                               │
                   │                                                               ▼
                   │                                        ┌──────────────────────────────────────────────┐
                   │                                        │ Citation & Evidence Validation Engine        │
                   │                                        │ - Claim-level evidence verification          │
                   │                                        │ - 1-indexed page & section mapping           │
                   │                                        └──────────────────────┬───────────────────────┘
                   │                                                               │
                   └───────────────────────────────┬───────────────────────────────┘
                                                   │
                                                   ▼
                                ┌──────────────────────────────────────────────┐
                                │ Conversation Persistence (SQLite Repository) │
                                │ - Messages, citations, audit telemetry       │
                                └──────────────────────┬───────────────────────┘
                                                       │
                                                       ▼
                        GROUNDED ANSWER + VERIFIED CITATIONS + TRANSPARENCY AUDIT
```

---

## 2. Document Ingestion & Structure-Aware Legal Chunking Pipeline

Flat, fixed-size 500-token/character chunking is fundamentally obsolete for contracts. Ingestion is upgraded to a structural extraction pipeline:

```text
Uploaded PDF Binary
        │
        ▼
┌──────────────────────────────────────────────┐
│ 1. Docling Document Parser                   │
│ - Preserves physical layout & page boundaries│
│ - Identifies headers, clauses, tables, lists │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 2. Structured Document Intermediate Model    │
│ - Document title, preamble, and parties      │
│ - Recitals                                   │
│ - Numbered clauses & subclauses (hierarchical)│
│ - Annexures & Schedules (e.g., ANNEXURE-I)   │
│ - Definitions block                          │
│ - Signatures & execution block               │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 3. Custom Structure-Aware Legal Chunker      │
│ - Keeps clause units intact with context     │
│ - Attaches parent section & document metadata│
│ - Assigns deterministic chunk_ids            │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ 4. Dual Indexing Engine                      │
│ ├── Dense Index: Gemini Embedding 2 → Qdrant │
│ └── Lexical Index: Tokenization → BM25 Index │
└──────────────────────────────────────────────┘
```

### Chunk Metadata Contract
Each chunk stored in Qdrant and the BM25 index contains:
* `document_id`: Unique identifier of the uploaded document.
* `chunk_id`: Structured unique ID (e.g. `doc_<id>_sec_<num>_chunk_<idx>`).
* `page_number`: 1-indexed primary page where the clause appears.
* `section_title`: Section heading (e.g., *"Termination"*, *"Annexure-I - Inventory of Fixtures"*).
* `section_number`: Section/clause identifier (e.g., *"Clause 14"*, *"Clause 21.2(a)"*, *"ANNEXURE-I"*).
* `text`: Full clause or section chunk text.
* `document_metadata`: Document title, filename, SHA-256 hash, and upload timestamp.

---

## 3. Technology Decisions & Provider Architecture

### 3.1 Technology Decisions Matrix

| Layer | Selected Technology | Rationale | Status |
|---|---|---|---|
| **Backend** | FastAPI / Python 3.12 | Existing high-performance async web framework | Current |
| **Document Parsing** | **Docling** | Preserves layout, document hierarchy, tables, annexures | Target (Replaces PyMuPDF) |
| **Chunking** | **Custom Structure-Aware Legal Chunker** | Avoids cutting clauses mid-sentence; isolates annexures & definitions | Target (Replaces flat chunker) |
| **Dense Embeddings** | **Gemini Embedding 2** (`text-embedding-004` / latest) | High semantic density, legal reasoning capacity | Target (Primary Provider) |
| **Vector DB** | **Qdrant** (Local development instance) | Filterable payload metadata, high search performance, isolated collections | Target (Replaces in-memory numpy) |
| **Lexical Search** | **BM25** (`rank-bm25` / scikit) | Essential for exact legal identifiers (`ANNEXURE-I`, `Clause 15`, names) | Target (Replaces pure TF-IDF) |
| **Fusion** | **Reciprocal Rank Fusion (RRF)** | Proven rank aggregation combining dense semantic + lexical candidates | Target |
| **LLM Provider** | **Gemini 3.8 Flash** | Fast, high-accuracy context following, cost-effective | Target (Primary Provider) |
| **Alternative LLM** | OpenAI (`gpt-4o` / `gpt-4o-mini`) | Existing provider abstraction support | Maintained as alternative |
| **Local Fallback** | Ollama | Optional future local fallback; NOT part of immediate implementation | Deferred |
| **Reranking** | Local Cross-Encoder | Avoids premature debugging complexity before hybrid baseline is proven | Deferred |
| **Persistence** | SQLite (`data/legal_qa.db` with WAL) | Durable conversation, message, citation, and profile store | Current / Preserved |
| **Frontend** | Existing Vanilla JS / HTML | Clean, responsive UI with conversation list and citation modal | Current / Preserved |

### 3.2 Provider Abstraction Pattern

The provider architecture is decoupled and configurable:

```text
EmbeddingProvider (Interface)
├── GeminiEmbeddingProvider (Primary: Gemini Embedding 2)
└── LocalEmbeddingProvider (Fallback: e.g. FastEmbed / BGE history)

LLMProvider (Interface)
├── GeminiLLMProvider (Primary: Gemini 3.8 Flash)
├── OpenAILLMProvider (Secondary: OpenAI models)
└── Future providers (e.g., Ollama - deferred)
```

**Key Architectural Rules:**
1. **Unified Pipeline:** Gemini and OpenAI do **NOT** have separate RAG pipelines. Both providers consume identical context structures generated by the hybrid retrieval engine.
2. **Provider-Independent Retrieval:** Ingestion, chunking, Qdrant indexing, BM25 retrieval, and RRF operate independently of the selected LLM provider.
3. **Environment Security:** All API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`) must remain environment variables. **Never hard-code API keys.**

---

## 4. Hybrid Retrieval & Reciprocal Rank Fusion (RRF)

### 4.1 Why Vector Search Alone Fails Legal QA
Legal documents require two distinct retrieval modalities:
1. **Exact Identifiers:** Questions inquiring about *"ANNEXURE-I"*, *"Clause 15"*, *"Security Deposit of Rs. 50,000"*, or *"John Doe"* frequently fail under pure vector similarity because the vector space smooths alphanumeric tokens into generic legal concepts. BM25 guarantees high ranking for exact keywords.
2. **Conceptual Queries:** Questions inquiring about *"What happens if the agreement ends early?"* or *"What are tenant liabilities on damage?"* require dense vector representations to match provisions phrased as *"Termination on Default"* or *"Indemnification and Repairs"*.

### 4.2 Reciprocal Rank Fusion Formulation
Given a query $q$:
1. Retrieve top $N$ dense candidates from Qdrant: $D = [d_1, d_2, \dots, d_N]$.
2. Retrieve top $N$ BM25 candidates from inverted index: $B = [b_1, b_2, \dots, b_N]$.
3. Compute the fused RRF score for each unique chunk $c$:
   $$RRF(c) = \frac{1}{60 + r_{dense}(c)} + \frac{1}{60 + r_{bm25}(c)}$$
   (where $r(c)$ is the 1-indexed rank, or $\infty$ if not retrieved in that channel).
4. Sort by descending $RRF(c)$ and select the top $K$ candidates for evidence fencing.

---

## 5. Question Routing Architecture

The question router eliminates the defect where general non-document inquiries (e.g., *"What is the day today?"*, *"What is Python?"*) enter retrieval and return false document refusals (*"Not stated in document"*).

```text
                         User Inbound Message
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │ Deterministic Pattern Matches │
                   │ - Greetings, system queries,  │
                   │   generic definitions         │
                   └───────────────┬───────────────┘
                                   │
                     ┌─────────────┴─────────────┐
                     ▼ Match                     ▼ No Match
           ┌───────────────────┐       ┌───────────────────────────────┐
           │ Route: GENERAL    │       │ Lightweight Classifier Check  │
           │ Direct LLM Invoke │       │ Document Question?            │
           │ (0 Doc Retrieval) │       └───────────────┬───────────────┘
           └───────────────────┘                       │
                                         ┌─────────────┴─────────────┐
                                         ▼ Yes                       ▼ No
                               ┌───────────────────┐       ┌───────────────────┐
                               │ Route: DOCUMENT   │       │ Route: GENERAL    │
                               │ Hybrid RAG Flow   │       │ Direct LLM Invoke │
                               └───────────────────┘       └───────────────────┘
```

---

## 6. Grounding, Answer Generation & Citations

### 6.1 Untrusted Context Fencing & Injection Defense
Retrieved chunks are formatted as inert data inside machine-readable XML fences:
```xml
<context_document_data document_id="doc_xyz">
  <chunk id="chunk_1" page="3" section="Clause 14 - Termination">
    Either party may terminate this agreement by providing thirty (30) days written notice...
  </chunk>
</context_document_data>
```
* The LLM prompt treats this data as strictly untrusted text.
* Prompt injections embedded in contracts cannot hijack system instructions.

### 6.2 Structured Answer States
Instead of fragile hardcoded strings (*"Not stated in document"*), the generation layer enforces conceptual response states:
* `supported`: All aspects of the inquiry are substantiated by retrieved chunks.
* `partially_supported`: Specific sub-questions are answered; unsupported elements are explicitly stated as not found.
* `insufficient_context`: Document context lacks evidence to ground an answer.

### 6.3 Citation Integrity
* Every claim must be tied to its supporting chunk with 1-indexed page number and section title.
* The system validates that cited chunks genuinely contain the factual basis of the claim.

---

## 7. Deferred Architectural Components

* **Reranking Engine:** Implementation of cross-encoder rerankers is **DEFERRED** until the Docling + structure-aware chunking + Gemini Embedding 2 + Qdrant + BM25 + RRF baseline is fully verified and benchmarked. Adding a reranker prematurely complicates retrieval debugging.
* **Ollama Local LLM:** Deferred until after Gemini and OpenAI provider parity is established.

---

## 8. Provider Abstraction & Migration Architecture

### 8.1 Target Architecture
The application layer is decoupled from concrete AI and vector database providers through provider protocols (`RAGProvider`, `LLMProvider`, `EmbeddingProvider`).

```text
Frontend
   ↓
FastAPI
   ↓
Application / Chat Service
   │
   ├──────────────→ RAGProvider
   │                    │
   │               ┌────┴────┐
   │               │         │
   │             Local      xAI
   │
   └──────────────→ LLMProvider
                        │
                 ┌──────┼──────┐
                 │      │      │
               Gemini OpenAI  xAI
```

### 8.2 Configuration & Provider Switching
Switching providers is controlled centrally via environment variables:

* **Current Development Configuration:**
  ```env
  RAG_PROVIDER=local
  LLM_PROVIDER=gemini
  ```

* **Future xAI Configuration:**
  ```env
  RAG_PROVIDER=xai
  LLM_PROVIDER=xai
  XAI_API_KEY="your-xai-api-key"
  ```

### 8.3 Migration Boundaries & Data Neutrality
1. **RAG Boundary (`RAGProvider`):** Ingestion, query retrieval, and document deletion are mediated through `app.providers.interfaces.RAGProvider`. The local implementation (`LocalRAGProvider`) wraps the existing Qdrant + BM25 + RRF pipeline. The xAI adapter (`XAIRAGProvider`) handles remote collections.
2. **Normalized Retrieval Results (`RetrievedChunk`):** Application services receive normalized `RetrievedChunk` dataclasses rather than Qdrant- or xAI-specific SDK objects.
3. **LLM Boundary (`LLMProvider`):** Generation is mediated through `app.providers.interfaces.LLMProvider` returning normalized `LLMResponse` objects.
4. **Stable Application Identifiers:** `document_id`, `conversation_id`, and session metadata remain application-owned and stable across provider migrations.
5. **No Premature xAI Spending:** When `RAG_PROVIDER=local`, xAI clients are never initialized and require zero xAI credentials or credits. When `RAG_PROVIDER=xai` without credentials, the system raises a clear configuration error rather than silently degrading.
