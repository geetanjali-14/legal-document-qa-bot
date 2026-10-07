# Legal Document Q&A Assistant

A local legal document question-and-answer application built with FastAPI. It lets you upload a PDF contract, search the relevant clauses, and ask grounded questions about the document while returning citations to the original source text.

## Features

- Upload legal PDFs
- Extract text and preserve page metadata
- Split large documents into searchable chunks
- Search within a single uploaded document
- Answer questions using the uploaded contract as the source of truth
- Return citations with document, page, section, and snippet
- Refuse to answer when the answer is not in the document
- Provide a browser-based frontend
- Run with a local mock LLM by default

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

## Default Configuration Notes

The app defaults to:

- `LLM_PROVIDER=mock` (supports `mock`, `openai`, `gemini`)
- `EMBEDDING_PROVIDER=tfidf` (supports `tfidf`, `fastembed`, `openai`)
- `DATABASE_URL=""` (defaults to safe SQLite with WAL mode at `data/legal_qa.db`; compatible with PostgreSQL in production)

## Additional Docs

The repo contains comprehensive documentation:

- [docs/PRD.md](docs/PRD.md) - Product Requirements Document covering milestones P0 through P4.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - System architecture, agent orchestrator, determinism tools, and security boundaries.
- [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) - Development plan, execution status, and verification metrics.
