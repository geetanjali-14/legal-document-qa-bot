# Product Requirements Document (PRD)
## Legal Document Q&A Assistant

* **Document Version:** 1.0.0
* **Status:** Draft / Planning Baseline
* **Author:** AI & Systems Architecture Team
* **Last Updated:** October 7, 2026

---

## 1. Product Overview

The **Legal Document Q&A Assistant** is an intelligent, document-grounded retrieval-augmented generation (RAG) application in Python. Its primary purpose is to allow users to securely upload legal documents (such as contracts, master services agreements, employment contracts, leases, and non-disclosure agreements) and ask natural-language questions regarding their contents.

The system synthesizes answers **strictly** from verified passages within the uploaded documents and provides traceable, verifiable citations (document name, page number, section, and text snippet) for every answer provided.

---

## 2. Problem Statement

Legal documents are dense, complex, and lengthy. Individuals, small business owners, and operational staff frequently encounter agreements spanning dozens or hundreds of pages. Identifying critical clauses—such as:
* Termination notice windows and trigger conditions
* Renewal deadlines and auto-renewal terms
* Governing law and arbitration venues
* Fee structures, payment terms, and late penalties
* Confidentiality durations and liability limitations

currently requires tedious manual review or expensive third-party consultation. 

Generic AI chatbots hallucinate terms, reference non-existent clauses, or draw upon general internet knowledge rather than the explicit language of the contract at hand. Users require an automated tool that provides answers **grounded exclusively** in their specific uploaded document, complete with verifiable page and section citations and explicit refusals when clauses are absent.

---

## 3. Product Goals

1. **Strict Document Grounding:** Eliminate hallucinations by constraining the language model to retrieved context chunks only.
2. **Verifiable Citations:** Provide exact document metadata (page number, section heading, text snippet) for all factual statements.
3. **Transparent Fallback & Refusal:** Explicitly decline to answer when a query refers to facts or clauses not present in the document.
4. **Frictionless Document Ingestion:** Allow users to upload standard PDF agreements and automatically extract text, preserve page boundaries, and index vectors within seconds.
5. **Document-Scoped Isolation:** Guarantee that queries executed against a specific document never retrieve or leak passages from other uploaded documents.
6. **Conversational Coherence:** Maintain basic conversational continuity across sequential queries without overriding document grounding.
7. **Maintainable & Extensible Architecture:** Modular service boundaries allowing interchangeable embedding providers, vector backends, and LLM providers.

---

## 4. Non-Goals

For the MVP, the product explicitly does **NOT** intend to:
* **Provide Legal Advice:** It is an analytical information-retrieval assistant, not a licensed attorney or a substitute for professional legal counsel.
* **Determine Legal Validity or Enforceability:** It will not declare whether a non-compete, penalty clause, or indemnity provision is legally enforceable in a court of law.
* **Predict Litigation Outcomes:** It does not forecast dispute results.
* **Autonomous External Legal Research:** It will not browse external statutory codes, case law, or legal databases (e.g., Westlaw, LexisNexis) unless integrated in future phases.
* **Automated Contract Drafting or Editing:** It does not generate redlines or write new contracts in MVP.

---

## 5. Target Users

### MVP Users
* **Individual Consumers & Small Business Owners:** Individuals seeking to understand commitments, deadlines, fee clauses, and renewal terms in contracts they signed or received.

### Future Users (Post-MVP)
* **In-House Legal & Compliance Teams:** First-pass triage and rapid clause verification across large contract repositories.
* **Human Resources & Procurement Staff:** Rapid verification of vendor SLA terms, non-disclosure expiration dates, and employee agreements.

---

## 6. Core User Journey

```text
       User opens Web UI
               ↓
    Uploads legal PDF agreement
               ↓
    Backend validates file (size, format, magic bytes)
               ↓
    PyMuPDF extracts pages & text (detects scanned/empty PDF)
               ↓
    Chunking engine splits text into semantic paragraphs (attaching Section & Page)
               ↓
    Embedding provider computes vector representations
               ↓
    Local Vector Store indexes embeddings and persists to disk
               ↓
    User selects active document and asks question
               ↓
    Retrieval service computes query vector & performs scoped cosine search
               ↓
    Context + question submitted to LLM with strict grounding prompt
               ↓
    System renders answer + verifiable citation cards in Web UI
```

---

## 7. Functional Requirements

### 7.1 Document Ingestion & Validation
* **FR-DOC-001 (Format Support):** The system shall accept PDF files (`.pdf`). Magic-byte validation (`%PDF`) is mandatory.
* **FR-DOC-002 (Size Enforcment):** The system shall reject files exceeding `MAX_FILE_SIZE_MB` (default: 25 MB).
* **FR-DOC-003 (Filename Sanitization):** Uploaded filenames must be sanitized to strip path-traversal sequences (`../`) and illegal filesystem characters.
* **FR-DOC-004 (Scanned Document Detection):** If a document contains zero or negligible extractable characters across pages, the system shall reject it with an explanatory message indicating that OCR is required.
* **FR-DOC-005 (Page Preservation):** Extracted text must strictly retain its 1-indexed page number from the original PDF.
* **FR-DOC-006 (Section Detection):** The chunking service must apply heuristic regex matching to identify legal section headers (e.g., `Section 1.`, `Article IV`, `2.1 Termination`).

### 7.2 Chunking & Indexing
* **FR-CHK-001 (Chunk Sizing):** The system shall create chunks based on `CHUNK_SIZE` (default 500 characters) and `CHUNK_OVERLAP` (default 100 characters), prioritizing natural paragraph breaks.
* **FR-CHK-002 (Metadata Attachment):** Each chunk shall carry: `chunk_id`, `document_id`, `document_name`, `page_number`, `section`, `text`, and `token_count`.
* **FR-CHK-003 (Document Isolation):** Vectors must be scoped per `document_id`. Search operations against Document A must never return chunks belonging to Document B.

### 7.3 Retrieval & Q&A
* **FR-RET-001 (Vector Retrieval):** Queries must be converted to embedding vectors and matched against document chunks using cosine similarity.
* **FR-RET-002 (Similarity Filtering):** Chunks with similarity below `SIMILARITY_THRESHOLD` (default: 0.1) shall be filtered out.
* **FR-RET-003 (Top-K Limit):** Retrieval shall return at most `TOP_K` relevant chunks (default: 4).
* **FR-QA-001 (Grounding Prompt):** The LLM must be instructed with a strict system prompt to answer only from provided context passages.
* **FR-QA-002 (Fallback / Refusal):** If the retrieved context contains insufficient information to answer the user question, the system must return:
  > *"I couldn't find enough information in the uploaded document to answer this question."*

### 7.4 Citations & Verification
* **FR-CIT-001 (Citation Generation):** Answers backed by retrieved context must return structured citations including:
  * Document Name
  * Page Number (1-indexed)
  * Section Title
  * Text Snippet (truncated cleanly up to 250 characters)
  * Relevance Score
* **FR-CIT-002 (No Citation on Refusal):** When the system declares insufficient context, no fabricated citation cards shall be displayed.

### 7.5 Document Management & UI
* **FR-UI-001 (Document List):** The user can view all indexed documents with page count and chunk count.
* **FR-UI-002 (Document Selection):** The user can select a document to activate chat mode.
* **FR-UI-003 (Document Deletion):** Deleting a document removes its physical PDF file, vector embeddings, chunk records, and metadata entry.
* **FR-UI-004 (Loading States):** The UI must display explicit loading indicators during document upload and chat response generation.

---

## 8. Legal Safety Requirements

1. **Mandatory Disclaimer:** Every chat response and UI view must display a prominent legal disclaimer:
   > *"This tool provides information extracted from uploaded legal documents and is not a substitute for formal legal advice from a qualified attorney."*
2. **Prohibition of Advisory Conclusions:** The model must distinguish explicit textual provisions from legal interpretations. It must never assert that a clause is "illegal" or "unenforceable"; it must state what the agreement text says.
3. **No Speculation:** The assistant must never extrapolate beyond the provided text to guess local case law, unstated clauses, or standard industry practices unless explicitly in the text.

---

## 9. Accuracy & Grounding Requirements

* **Zero Hallucination Tolerance:** The model must not invent dollar amounts, notice windows, dates, parties, or contractual duties.
* **Metadata Integrity:** Page numbers in citations must correspond exactly to the page from which the text was extracted in the physical PDF.
* **Negative Question Testing:** Queries regarding topics not in the agreement (e.g., spacecraft operations in a commercial software agreement) must trigger the safe fallback response.

---

## 10. Security & Privacy Requirements

### MVP Security Controls
* **Secret Protection:** API keys and sensitive settings are strictly read via `.env` and kept out of version control (`.gitignore`).
* **Input Sanitization:** Filenames and user questions are sanitized against path traversal and buffer overflows.
* **File Upload Constraints:** Enforces 25 MB file size limit and `%PDF` magic-byte verification.
* **DoS Protection:** Caps maximum chunks per document at 5,000 to prevent server memory exhaustion.
* **No Sensitive Data Logging:** Full document bodies and customer prompts are excluded from operational logs.

### Production / Post-MVP Requirements
* **Authentication & Authorization:** Secure user accounts, JWT sessions, and document ownership checks.
* **Tenant Isolation:** Enforce strict organizational data partitioning in multi-tenant environments.
* **Rate Limiting:** Protect `/api/documents/upload` and `/api/chat` against brute-force abuse and API budget exhaustion.
* **CORS Hardening:** Restrict origins to approved production domain origins.

---

## 11. Non-Functional Requirements

* **Performance:** Document ingestion (under 10 pages) completed in under 3 seconds using local embeddings. Query retrieval and mock response generation completed in under 500ms.
* **Reliability:** Graceful error handling for corrupt PDFs, missing environment keys, and network timeouts without server crashes.
* **Maintainability:** Modular architecture adhering to single-responsibility service patterns and Pydantic schema validation.
* **Portability:** Container-ready Python application capable of running locally or on Linux server environments without non-standard native OS packages.

---

## 12. MVP Scope (Baseline)

The current MVP scope encompasses:
* FastAPI backend with CORS, lifespan management, and static file mounting.
* PyMuPDF text & page extractor with scanned document heuristic detection.
* Paragraph & legal section chunking service.
* In-memory + disk-persisted vector store (`.npy` + `.json`).
* Embedding provider support: TF-IDF (local default), Mock (tests), and OpenAI.
* LLM provider support: Mock (local deterministic) and OpenAI (`gpt-4o-mini`).
* Verifiable citation generation engine.
* Document upload, listing, retrieval, and deletion APIs.
* Vanilla HTML/CSS/JS frontend dashboard.

---

## 13. Post-MVP Features (Roadmap)

1. **OCR Pipeline:** Integration of Tesseract or cloud OCR for image-based/scanned PDFs.
2. **Dense Local Embeddings:** Integration of HuggingFace / ONNX local sentence transformers (e.g., `fastembed`, `bge-small-en`) to replace TF-IDF without cloud API dependencies.
3. **Conversational Query Reformulation:** Contextualizing follow-up questions before embedding retrieval.
4. **Relational Database Storage:** Migration from file-based JSON metadata to SQLite or PostgreSQL with SQLAlchemy.
5. **Authentication & Multi-Tenancy:** User accounts, roles, and isolated workspaces.
6. **Multi-Document Comparison:** Cross-document search and redline/variance analysis.
7. **Additional Providers:** Native integration for Google Gemini and Anthropic Claude.

---

## 14. Acceptance Criteria

| ID | Given | When | Then |
|---|---|---|---|
| **AC-01** | A valid text-based legal PDF | User uploads file via UI or API | File is extracted, chunked, and indexed with status `processed`. |
| **AC-02** | A scanned/image-only PDF | User uploads file | File is rejected with a 422 HTTP error explaining OCR requirement. |
| **AC-03** | An indexed legal document | User asks a question with known facts in the document | System returns a grounded answer containing the exact facts. |
| **AC-04** | An indexed legal document | System answers a question | System returns one or more citation cards with matching document, page, section, and snippet. |
| **AC-05** | An indexed legal document | User asks a question about topics completely absent from the document | System returns the standard refusal message and zero citations. |
| **AC-06** | Two separate indexed documents | User queries Document A | Retrieved chunks are exclusively from Document A, never from Document B. |
| **AC-07** | An indexed document | User clicks delete | Document file, vectors, chunk records, and metadata are removed completely. |
| **AC-08** | A non-PDF file (e.g. `.exe`) | User attempts upload | File is rejected immediately with a 400 Bad Request error. |

---

## 15. Known Limitations (From Audit)

1. **OCR Not Implemented:** Scanned contracts without an embedded text layer cannot be processed.
2. **TF-IDF Vocabulary Dependency:** Local embeddings rely on lexical term overlap rather than semantic deep representations.
3. **Lack of Query Reformulation:** Follow-up questions (e.g., *"What happens if I don't give it?"*) do not resolve ambiguous pronouns prior to vector retrieval.
4. **File-Based Metadata Storage:** `documents_meta.json` lacks ACID transactions and concurrency safeguards under heavy load.
5. **Mock LLM Sentence Splitting:** Test suite currently records 1 failure in mock sentence extraction during offline integration testing.
6. **Unauthenticated:** Endpoints are publicly accessible on the local interface.

