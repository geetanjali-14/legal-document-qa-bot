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

## Run the Test Suite

From the project root:

```bash
PYTHONPATH=. ./venv/bin/pytest -q
```

At the time of writing, the verified baseline is:

- 71 passed
- 1 warning
- 0 failed

## Default Configuration Notes

The app defaults to:

- `LLM_PROVIDER=mock`
- `EMBEDDING_PROVIDER=tfidf`

This makes the local app easier to test without external API keys. If you want to switch to OpenAI or another provider, update the values in `.env`.

## Troubleshooting

### App fails to start

Check whether dependencies are installed:

```bash
pip install -r requirements.txt
```

Also confirm the virtual environment is active.

### PDF upload is rejected

Make sure the file is a real PDF and ends with `.pdf`.

### No results returned

- confirm the document uploaded successfully
- verify the `document_id`
- ask a question directly supported by the document content

### Tests fail

Run this again from the project root:

```bash
PYTHONPATH=. ./venv/bin/pytest -q
```

## Additional Docs

The repo also contains deeper product and technical documentation here:

- [docs/PRD.md](docs/PRD.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)

## Notes

This project is a working local legal document Q&A system for document-grounded retrieval and citation-based answers. It is best suited for local development and demos rather than production deployment without additional security, authentication, and deployment hardening.
