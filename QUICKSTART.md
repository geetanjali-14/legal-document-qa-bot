# Quick Start

This is the fastest way to run the app locally and verify that the current implementation works.

## 1) Enter the project folder

```bash
cd '/home/rails/Work/Legal QA chatbot'
```

## 2) Activate the virtual environment

Use the project’s existing environment:

```bash
source venv/bin/activate
```

If the environment does not exist yet, create it first:

```bash
python3 -m venv venv
source venv/bin/activate
```

## 3) Start the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open the app here:

```text
http://localhost:8000
```

## 4) Check the API health

In another terminal:

```bash
echo "Checking backend health..."
curl http://localhost:8000/api/health
```

Expected result: a JSON object with a healthy status.

## 5) Create a sample contract for testing

```bash
python scripts/create_test_pdf.py
```

This creates a sample PDF at:

```text
documents/synthetic_contract.pdf
```

## 6) Upload the document

```bash
curl -X POST "http://localhost:8000/api/documents/upload" \
  -F "file=@documents/synthetic_contract.pdf"
```

This returns a document record and a `document_id`.

## 7) Ask a question

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "PASTE_DOCUMENT_ID_HERE",
    "question": "What is the termination notice period?",
    "top_k": 4
  }'
```

Try these prompts too:

- What state governs the agreement?
- What is the confidentiality period?
- When is payment due?

## 8) Run the full test suite

```bash
PYTHONPATH=. ./venv/bin/pytest -q
```

Verified baseline:

- 71 passed
- 1 warning
- 0 failed

## Common issues

### If the app won't start

```bash
pip install -r requirements.txt
```

### If the document upload fails

Make sure the file is a real PDF with a `.pdf` extension.

### If questions return no answer

Check the uploaded document ID and ensure the question is actually present in the document text.

## Summary

This is the shortest path to:

- run the app locally
- upload a contract
- ask grounded legal questions
- verify the system with the included tests
