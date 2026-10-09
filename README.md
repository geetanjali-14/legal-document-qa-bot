# Legal Document Q&A Assistant

A local legal document question-and-answer application built with FastAPI. It lets you upload a PDF contract, search the relevant clauses, and ask grounded questions about the document while returning citations to the original source text.

## Features

- Upload and parse legal PDFs and contracts with structure-aware chunking
- Dense semantic search (Gemini Embedding 2 / FastEmbed) + BM25 keyword search fused via Reciprocal Rank Fusion (RRF)
- Decoupled provider architecture (`RAGProvider` and `LLMProvider`) supporting Local Qdrant, xAI, Gemini, OpenAI
- Versioned, standalone REST API namespace (`/api/v1`) for seamless integration with external applications
- Grounded question answering with precise page, clause, section, and snippet citations
- Built-in multi-turn conversation management
- Browser-based frontend UI dashboard
- Comprehensive production migration guide ([PRODUCTION_MIGRATION.md](file:///home/rails/Work/Legal%20QA%20chatbot/PRODUCTION_MIGRATION.md)) and standalone integration guide ([INTEGRATION.md](file:///home/rails/Work/Legal%20QA%20chatbot/INTEGRATION.md))

## Project Structure

```text
.
├── app/
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── services/
│   └── main.py
├── data/
│   ├── uploads/
│   └── vector_store/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT_PLAN.md
│   └── PRD.md
├── frontend/
├── scripts/
│   └── create_test_pdf.py
├── tests/
├── .env.example
├── requirements.txt
├── README.md
└── .gitignore
```

## Prerequisites

- Python 3.12
- pip
- A local terminal

## Quick Start

### 1) Clone and enter the project

```bash
cd /path/to/Legal\ QA\ chatbot
```

### 2) Create or activate the virtual environment

This repo already includes a working virtual environment in `venv`, so the usual setup is:

```bash
source venv/bin/activate
```

If you need to create one fresh instead, run:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Configure environment variables

Copy the sample env file if you want to override defaults:

```bash
cp .env.example .env
```

The default app settings work for local development. The app is configured to use the mock LLM by default, which is suitable for local testing.

### 5) Start the application

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:

```text
http://localhost:8000
```

The frontend should load in the browser.

## Health Check

Before uploading documents, confirm the API is running:

```bash
curl http://localhost:8000/api/health
```

You should receive a JSON response with the app status and configured providers.

## Create a Sample Contract for Testing

The project includes a synthetic contract generator:

```bash
python scripts/create_test_pdf.py
```

This creates a sample PDF at:

```text
documents/synthetic_contract.pdf
```

## Upload a Document

### Using the browser

- Open the app in the browser
- Use the upload panel to upload the sample PDF

### Using the API

```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "file=@documents/synthetic_contract.pdf"
```

The response will include a `document_id` that you can use for future questions.

## Ask Questions About the Document

### Example request

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "PASTE_DOCUMENT_ID_HERE",
    "question": "What is the termination notice period?",
    "top_k": 4
  }'
```

### Example questions

- What is the termination notice period?
- Which state governs the agreement?
- What is the confidentiality period?
- When is payment due?
- What is the governing law?

The app should return:

- the answer
- the relevant source snippet
- page number
- section name
- confidence status

## Run the Test Suite & Offline Evaluation Benchmark

From the project root:

```bash
# Run pytest verification suite (159 passing tests)
PYTHONPATH=. ./venv/bin/pytest -v

# Run the Legal RAG Offline Evaluation Benchmark (31/31 passing cases)
PYTHONPATH=. ./venv/bin/python tests/evaluation/run_benchmark.py
```

Current verified baseline:
- **Pytest**: 159 passed, 0 failed
- **Offline RAG Benchmark**: 31/31 evaluated passed (100% across Direct Fact, Multi-Clause, Unanswerable, Adversarial Injection, Citation Integrity, Defined Term, Structure Navigation, Obligations, Risk Analysis, and Temporal Reasoning)

## Production Deployment & Containerization

A hardened multi-stage Docker container is provided:

```bash
# Build the production Docker image
docker build -t legal-doc-intelligence:latest .

# Run container with persistent storage
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@db:5432/legal_qa \
  -v $(pwd)/data:/app/data \
  legal-doc-intelligence:latest
```

Healthcheck is actively monitored at `/api/health`.

## Project Status & Architecture Direction

> **Current Status:** Functional MVP with a known RAG correctness/reliability gap on complex legal documents.  
> **Current Priority:** Implement and verify the target Hybrid RAG Core inside the existing application (see [docs/DEVELOPMENT_PLAN.md](file:///home/rails/Work/Legal%20QA%20chatbot/docs/DEVELOPMENT_PLAN.md)).

The target production pipeline combines:
- **Parsing:** Docling (replacing line-by-line PyMuPDF)
- **Chunking:** Custom structure-aware legal chunking (preserving titles, parties, recitals, clauses, annexures, definitions)
- **Embeddings:** Gemini Embedding 2 as primary dense provider
- **Vector DB:** Qdrant (local instance for development)
- **Keyword Retrieval:** BM25 lexical index
- **Hybrid Fusion:** Reciprocal Rank Fusion (RRF)
- **Question Routing:** Deterministic & classified routing (general queries bypass document retrieval, eliminating false refusals)
- **LLM Generation:** Gemini 3.8 Flash as primary provider, with strict evidence grounding and structured answer status
- **Reranking:** Explicitly deferred until the hybrid baseline is verified

## Default Configuration Notes

The app supports configurable providers via environment variables:

- `LLM_PROVIDER=gemini` (supports `gemini` [Gemini 3.8 Flash primary], `openai`, and `mock` for testing)
- `EMBEDDING_PROVIDER=gemini` (supports `gemini` [Gemini Embedding 2 primary], `fastembed`, `tfidf` [legacy])
- `QDRANT_URL=http://localhost:6333` (local Qdrant vector database)
- `DATABASE_URL=""` (defaults to safe SQLite with WAL mode at `data/legal_qa.db`; compatible with PostgreSQL in production)

All API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`) must be set via environment variables.

## Additional Docs

The repo contains comprehensive documentation:

- [docs/PRD.md](file:///home/rails/Work/Legal%20QA%20chatbot/docs/PRD.md) - Product Requirements Document (v4.0.0).
- [docs/ARCHITECTURE.md](file:///home/rails/Work/Legal%20QA%20chatbot/docs/ARCHITECTURE.md) - Target System Architecture & Retrieval Pipeline (v4.0.0).
- [docs/DEVELOPMENT_PLAN.md](file:///home/rails/Work/Legal%20QA%20chatbot/docs/DEVELOPMENT_PLAN.md) - Phased Implementation Roadmap & Validation Plan (Phases 0–10).
