# Technical Architecture Document
## Legal Document Q&A Assistant

* **Document Version:** 1.0.0
* **Status:** Draft / Technical Baseline
* **Author:** Lead Backend & Security Architect
* **Last Updated:** October 7, 2026

---

## 1. Architecture Overview

The **Legal Document Q&A Assistant** is organized as a modular, decoupled Python system built on FastAPI. It employs an in-process Retrieval-Augmented Generation (RAG) architecture tailored for legal document analysis.

```text
                               +----------------------------+
                               |     Browser Client         |
                               | (HTML5 / Vanilla JS / CSS) |
                               +--------------+-------------+
                                              | HTTP / REST
                                              v
+------------------------------------------------------------------------------------------+
|                                    FastAPI Application                                   |
|                                                                                          |
|    +----------------------+  +----------------------+  +-----------------------------+   |
|    | routes_health.py     |  | routes_documents.py  |  | routes_chat.py              |   |
|    +----------------------+  +----------+-----------+  +--------------+--------------+   |
|                                         |                             |                  |
|                                         v                             v                  |
|                              +----------------------+  +-----------------------------+   |
|                              | DocumentService      |  | RetrievalService            |   |
|                              +----------+-----------+  +--------------+--------------+   |
|                                         |                             |                  |
|                    +--------------------+--------------------+        |                  |
|                    |                    |                    |        |                  |
|                    v                    v                    v        v                  |
|          +------------------+ +-------------------+ +--------------------+               |
|          | PDFService       | | ChunkingService   | | VectorStore        |               |
|          | (PyMuPDF)        | | (Section-aware)   | | (Scoped Cosine)    |               |
|          +------------------+ +-------------------+ +---------+----------+               |
|                                                               |                          |
|                                                               v                          |
|                                                     +--------------------+               |
|                                                     | EmbeddingService   |               |
|                                                     | (TF-IDF / OpenAI)  |               |
|                                                     +--------------------+               |
|                                                                                          |
|          +---------------------------------------------------------------+               |
|          | LLMService (System Prompt + Mock / OpenAI)                    |               |
|          | CitationService (Verifiable metadata & snippets)             |               |
|          +---------------------------------------------------------------+               |
+------------------------------------------------------------------------------------------+
                                              |
                       +----------------------+----------------------+
                       |                                             |
                       v                                             v
          +-------------------------+                   +-------------------------+
          | data/uploads/           |                   | data/vector_store/      |
          | Physical PDF Files      |                   | .npy vectors            |
          | documents_meta.json     |                   | .json chunks            |
          +-------------------------+                   +-------------------------+
```

---

## 2. Current vs. Planned Architecture

| Component | Current State (Baseline) | Planned State (Target) |
|---|---|---|
| **API Framework** | FastAPI 0.142 + Uvicorn 0.54 | FastAPI + Uvicorn / Gunicorn production workers |
| **PDF Extraction** | PyMuPDF text & page parsing + scan heuristic | PyMuPDF + Tesseract / Cloud OCR fallback pipeline |
| **Section Detection** | Regex-based heading patterns | Hybrid rule-based + layout structure parser |
| **Embeddings** | TF-IDF (local default), OpenAI, Mock | Local dense embeddings (`fastembed`/HuggingFace) + OpenAI + Gemini |
| **Vector Store** | In-memory dict + `.npy` / `.json` files | SQLite-vss / Qdrant / pgvector |
| **LLM Inference** | Mock LLM & OpenAI (`gpt-4o-mini`) | OpenAI + Google Gemini + Anthropic Claude + local Ollama |
| **Metadata Storage** | File-based JSON (`documents_meta.json`) | Relational database (SQLite / PostgreSQL + SQLAlchemy) |
| **Query Engine** | Single-turn vector lookup | Conversational query contextualization / rewrite engine |
| **UI** | Vanilla JS Single Page Dashboard | Modern responsive SPA / React or optimized Vanilla UI |
| **Auth & Security** | Unauthenticated, input sanitization | JWT Bearer auth, RBAC, tenant data isolation, rate limiting |

---

## 3. Current Component Architecture

The codebase strictly segregates responsibilities across modular directories:

```text
app/
├── api/
│   ├── routes_health.py        # Health diagnostics & active provider reporting
│   ├── routes_documents.py     # Document ingestion, status queries, deletion
│   └── routes_chat.py          # Grounded question answering & citation synthesis
├── core/
│   ├── config.py               # Pydantic Settings reading .env configurations
│   └── logging.py              # Structured console logging
├── models/
│   ├── document.py             # PageContent, DocumentChunk, DocumentMetadata
│   ├── chat.py                 # Message, Citation, ChatRequest, ChatResponse
│   └── response.py             # Standard ApiResponse envelope
├── services/
│   ├── pdf_service.py          # PDF text extraction and scanned document detection
│   ├── chunking_service.py     # Section-aware paragraph chunking
│   ├── embedding_service.py    # Embedding provider abstraction (TF-IDF, Mock, OpenAI)
│   ├── vector_store.py         # Document-scoped vector persistence and search
│   ├── retrieval_service.py    # Similarity threshold matching & top-k ranking
│   ├── citation_service.py     # Traceable citation formatting
│   ├── llm_service.py          # Strict system prompt enforcement & LLM provider
│   └── document_service.py     # High-level ingestion and storage coordinator
└── main.py                     # Lifespan service wiring, CORS, and static file serving
```

---

## 4. Document Ingestion Pipeline

When a user uploads a PDF file to `POST /api/documents/upload`, it transitions through sequential processing stages:

```text
                  +----------------------------------+
                  | User Uploads PDF Stream (Bytes)  |
                  +-----------------+----------------+
                                    |
                                    v
                  +----------------------------------+
                  | 1. Validation                    |
                  | - Check magic bytes (%PDF)       |
                  | - Enforce MAX_FILE_SIZE_MB       |
                  | - Sanitize filename              |
                  +-----------------+----------------+
                                    |
                                    v
                  +----------------------------------+
                  | 2. Physical Storage              |
                  | - Save to data/uploads/<doc_id>  |
                  +-----------------+----------------+
                                    |
                                    v
                  +----------------------------------+
                  | 3. PyMuPDF Extraction            |
                  | - Iterate 1-indexed pages        |
                  | - Clean hyphens & whitespaces    |
                  | - Reject if scanned (no text)    |
                  +-----------------+----------------+
                                    |
                                    v
                  +----------------------------------+
                  | 4. Chunking Service              |
                  | - Detect section headers         |
                  | - Group paragraphs <= CHUNK_SIZE |
                  | - Attach page & section metadata |
                  +-----------------+----------------+
                                    |
                                    v
                  +----------------------------------+
                  | 5. Embedding Generation          |
                  | - Compute NxDim matrix vectors   |
                  +-----------------+----------------+
                                    |
                                    v
                  +----------------------------------+
                  | 6. Vector Store Indexing         |
                  | - L2 normalize vectors           |
                  | - Save <doc_id>_vectors.npy      |
                  | - Save <doc_id>_chunks.json      |
                  +-----------------+----------------+
                                    |
                                    v
                  +----------------------------------+
                  | 7. Metadata Commitment           |
                  | - Record in documents_meta.json  |
                  | - Return 201 Created Response    |
                  +----------------------------------+
```

### Metadata Preserved in Every Chunk
```json
{
  "chunk_id": "chk_a1b2c3d4e5f6",
  "document_id": "doc_9f8e7d6c5b4a",
  "document_name": "master_services_agreement.pdf",
  "page_number": 2,
  "section": "2.1 Termination for Convenience",
  "text": "Either party may terminate this Agreement without cause...",
  "token_count": 68
}
```

---

## 5. RAG & Grounding Architecture

```text
User asks: "What is the termination notice period?"
                       |
                       v
         +-----------------------------+
         | Question Embedding          |
         | (1 x Dim vector)            |
         +-------------+---------------+
                       |
                       v
         +-----------------------------+
         | Vector Search               |
         | Filter: document_id == doc  |
         | Metric: Cosine Similarity   |
         +-------------+---------------+
                       |
                       v
         +-----------------------------+
         | Threshold Gate              |
         | Score >= SIMILARITY_THRESH  |
         +-------------+---------------+
                       |
        +--------------+--------------+
        |                             |
 (Passed >= 1 Chunk)           (0 Chunks Passed)
        |                             |
        v                             v
+-----------------------+     +-------------------------------+
| Top-K Chunks Selected |     | Fallback / Refusal            |
+-----------+-----------+     | "I couldn't find enough       |
            |                 | information in the uploaded   |
            v                 | document to answer..."        |
+-----------------------+     +-------------------------------+
| LLM Context Assembly  |
| Strict System Prompt  |
+-----------+-----------+
            |
            v
+-----------------------+
| LLM Generation        |
| Grounded Answer       |
+-----------+-----------+
            |
            v
+-----------------------+
| Citation Service      |
| Extract page, section,|
| snippet & score       |
+-----------------------+
```

### Hallucination Controls
1. **Document-Scoped Querying:** Chunks are selected only from the target document.
2. **Threshold Filtering:** Below-threshold similarity drops irrelevant chunks, preventing the model from hallucinating over noisy text.
3. **Strict System Prompt:** Explicitly commands the LLM:
   > *"Answer the user's question using ONLY the provided document context below. Do not use unsupported facts. Do not invent clauses, dates, amounts, obligations, rights, or legal conclusions."*
4. **Programmatic Refusal Recognition:** If the LLM generates a refusal message, confidence is downgraded to `insufficient_context` and citations are suppressed.

---

## 6. Embedding Architecture

The system abstracts vector representations behind the [`BaseEmbeddingProvider`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/embedding_service.py) interface:

### 1. TF-IDF Provider (`TFIDFEmbeddingProvider`)
* **Mechanism:** Uses scikit-learn `TfidfVectorizer` to fit an in-memory n-gram vocabulary and output normalized frequency-inverse document frequency sparse/dense matrices.
* **Benefits:** Requires zero external APIs, zero cost, runs offline, fast on CPU.
* **Limitations:** Lexical only; struggles with semantic synonyms (e.g. matching *"cancel contract"* to *"terminate agreement"* if words do not overlap).

### 2. OpenAI Provider (`OpenAIEmbeddingProvider`)
* **Mechanism:** Calls OpenAI `/v1/embeddings` endpoint using model `text-embedding-3-small`.
* **Benefits:** High semantic fidelity, robust cross-clause conceptual retrieval.
* **Requirements:** External API key and network connectivity.

### 3. Mock Provider (`MockEmbeddingProvider`)
* **Mechanism:** Deterministic token-hash vector projection.
* **Purpose:** High-speed, reproducible unit test execution.

---

## 7. LLM Provider Architecture

The system abstracts generation behind the [`BaseLLMProvider`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/llm_service.py) interface:

* **Mock Provider (`MockLLMProvider`):** Employs rule-based sentence matching against the provided context. Returns grounded snippets for known keywords and refuses unknown queries.
* **OpenAI Provider (`OpenAILLMProvider`):** Dispatches context, conversation history, and user prompts to OpenAI chat completions (`gpt-4o-mini`).

> **Architectural Audit Note:** Google Gemini is **NOT** currently implemented in the codebase. Anthropic and Ollama are mentioned in configuration literals but have no backing provider classes.

---

## 8. Vector Store Architecture

The [`VectorStore`](file:///home/rails/Work/Legal%20QA%20chatbot/app/services/vector_store.py) manages vector persistence and similarity computation:

* **Storage Format:** NumPy binary array (`.npy`) storing the $N \times D$ normalized matrix and JSON (`.json`) storing chunk objects.
* **Cosine Similarity Calculation:**
  $$\text{sim}(\vec{q}, \vec{d}) = \frac{\vec{q} \cdot \vec{d}}{\|\vec{q}\|_2 \|\vec{d}\|_2}$$
  Because stored chunk vectors are pre-normalized upon insertion ($\|\vec{d}\|_2 = 1$), search simplifies to an efficient matrix-vector dot product:
  $$\text{similarities} = M_{\text{doc}} \cdot \hat{q}^T$$
* **Multi-Document Isolation:** The store indexes vectors under separate dictionary keys and distinct filenames (`<doc_id>_vectors.npy`). Cross-document leakage is physically prevented.

---

## 9. API Architecture

All endpoints adhere to the standard envelope model:

```json
{
  "success": true,
  "message": "Operation status description",
  "data": { ... },
  "error": null
}
```

### Endpoints
* `GET /api/health`: Operational liveness and active provider status.
* `POST /api/documents/upload`: Multipart PDF upload, parsing, and indexing.
* `GET /api/documents`: List of all indexed documents with statistics.
* `GET /api/documents/{document_id}`: Detailed metadata for a single document.
* `DELETE /api/documents/{document_id}`: Deletion of document metadata, PDF file, and vector index.
* `POST /api/chat`: Grounded Q&A against a specified `document_id`.

---

## 10. Frontend Architecture

The frontend is a lightweight Single Page Application (SPA) located in `frontend/`:
* **Markup (`index.html`):** Split-view layout featuring a document management sidebar and an active conversation stream.
* **Styles (`static/style.css`):** Responsive dark-theme styling with dedicated card components for source citations.
* **Client Logic (`static/app.js`):** Vanilla JS handling multipart file uploads, asynchronous polling, active document switching, and markdown message rendering.

---

## 11. Storage & Persistence Architecture

The current implementation uses a local filesystem structure:
* `data/uploads/`: Original uploaded PDF documents.
* `data/uploads/documents_meta.json`: Document catalog and ingestion statistics.
* `data/vector_store/`: Chunk JSON files and NumPy vector binaries.

### Storage Limitations
* Concurrency hazards on updating `documents_meta.json`.
* Filesystem scaling constraints when managing thousands of documents.

---

## 12. Security Architecture

### Existing Controls
1. **Filename Sanitization:** Strips directory separators and non-whitelisted characters via regex.
2. **Magic-Byte Header Check:** Validates that incoming streams begin with `%PDF`.
3. **Payload Capping:** 25 MB file limit and 5,000 chunk cap per document.
4. **Configuration Safety:** API credentials isolated in `.env` and excluded from git.

### Production Gaps
* Missing authentication and authorization tokens.
* Open CORS policy (`allow_origins=["*"]`).
* Absence of IP-based or token-based API rate limiting.

---

## 13. Scalability Considerations

* **Compute:** Vector math using NumPy is fast for documents under 500 pages. For enterprise-scale repositories (>100,000 documents), migration to an indexed vector database (e.g., pgvector or Qdrant) is required.
* **Memory Footprint:** In-memory vector dictionaries consume memory proportional to total indexed chunks across active documents.

---

## 14. Planned Target Architecture (Post-MVP)

```text
                             +------------------------+
                             | React / Modern Web SPA |
                             +-----------+------------+
                                         | HTTPS (Bearer JWT)
                                         v
                             +------------------------+
                             | API Gateway & WAF      |
                             | Rate Limiting & Auth   |
                             +-----------+------------+
                                         |
                                         v
                             +------------------------+
                             | FastAPI Cluster        |
                             +-----------+------------+
                                         |
            +----------------------------+----------------------------+
            |                            |                            |
            v                            v                            v
+-----------------------+    +-----------------------+    +-----------------------+
| Relational Database   |    | Cloud Object Storage  |    | Dedicated Vector DB   |
| (PostgreSQL + ACID)   |    | (S3 / Cloud Storage)  |    | (Qdrant / pgvector)   |
| Documents & Users     |    | Encrypted PDF Files   |    | HNSW Index Search     |
+-----------------------+    +-----------------------+    +-----------------------+
            |                            |                            |
            +----------------------------+----------------------------+
                                         |
                                         v
                             +------------------------+
                             | Query Contextualizer   |
                             | (Multi-turn rewrite)   |
                             +-----------+------------+
                                         |
                                         v
                             +------------------------+
                             | Multi-LLM Provider     |
                             | (Gemini / Claude / GPT)|
                             +------------------------+
```

---

## 15. Architecture Decision Records (ADRs)

### ADR-01: FastAPI for Backend Framework
* **Context:** High-performance REST API needed with async support and automatic OpenAPI docs.
* **Decision:** Adopt FastAPI + Pydantic.
* **Consequences:** Clean schema validation, typed models, native async endpoints.

### ADR-02: Document-Scoped Vector Isolation
* **Context:** Legal users must not leak information between distinct agreements.
* **Decision:** Enforce `document_id` scoping at the vector search interface level.
* **Consequences:** Search cannot cross document boundaries, ensuring tenant and agreement privacy.

### ADR-03: Provider Abstraction for Embeddings & LLMs
* **Context:** Cloud API costs and offline testing requirements require decoupling business logic from vendors.
* **Decision:** Implement abstract base classes (`BaseEmbeddingProvider`, `BaseLLMProvider`).
* **Consequences:** Seamless transitions between local TF-IDF, OpenAI, and future providers without altering ingestion or retrieval pipelines.

