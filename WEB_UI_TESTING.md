# Web UI Testing Guide

This guide walks through the browser-based testing flow for the Legal Document Q&A Assistant.

## Prerequisites

- Project dependencies installed
- Virtual environment activated
- App running locally

## 1) Start the app

From the project root:

```bash
cd '/home/rails/Work/Legal QA chatbot'
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:

```text
http://localhost:8000
```

You should see the main UI with:

- a left-side upload panel
- a document list
- a chat panel on the right

## 2) Generate a sample legal document

In a second terminal:

```bash
cd '/home/rails/Work/Legal QA chatbot'
source .venv/bin/activate
python scripts/create_test_pdf.py
```

This creates:

```text
documents/synthetic_contract.pdf
```

## 3) Upload the document in the web UI

In the browser:

1. Find the upload area on the left sidebar
2. Click “browse” or drag the PDF into the drop zone
3. Select `documents/synthetic_contract.pdf`
4. Wait for the upload status message

You should see a success message like:

- upload completed
- document indexed successfully

## 4) Select the uploaded document

After upload, the document should appear in the “Your Documents” list.

Click the document row to select it.

When selected, the UI should:

- show the document name in the active document banner
- enable the question box
- enable the Ask button

## 5) Ask a valid question

Type a question that appears directly in the contract, for example:

```text
What is the termination notice period?
```

or

```text
Which state governs the agreement?
```

Then press Ask.

Expected result:

- the user message appears in the chat
- the assistant replies with an answer
- the answer is supported by document text
- a source section appears with citations
- the citation includes page number and section context

## 6) Confirm citation behavior

Look for the answer card and the sources section.

Each source should show:

- page number
- section name
- snippet from the contract
- document title

This confirms the app is grounding the answer in the uploaded PDF rather than guessing.

## 7) Test a question not in the document

Ask something unrelated to the contract, for example:

```text
What is the launch schedule for a rocket?
```

Expected result:

- the system says it could not find enough information
- no citations are returned
- the answer is a refusal, not a made-up legal answer

## 8) Check document deletion

In the document list:

1. Click the trash icon next to the uploaded document
2. Confirm the deletion prompt

Expected result:

- the document disappears from the list
- the active document clears
- the chat input becomes disabled again

## 9) Smoke test checklist

Use this quick checklist after each change:

- [ ] App loads at http://localhost:8000
- [ ] Upload accepts a valid PDF
- [ ] Document is shown in the document list
- [ ] Selecting a document enables the question input
- [ ] Valid legal question returns grounded answer
- [ ] Source citations appear
- [ ] Unrelated question returns insufficient-context response
- [ ] Deleting document clears it from the UI

## 10) Run the automated tests as a backend check

Even though this is the UI guide, always keep the backend tests in mind:

```bash
cd '/home/rails/Work/Legal QA chatbot'
PYTHONPATH=. ./venv/bin/pytest -q
```

Verified baseline:

- 71 passed
- 1 warning
- 0 failed

## Recommended manual test cases

For stable UI validation, run these exact questions:

1. What is the termination notice period?
2. Which state governs the agreement?
3. What is the confidentiality period?
4. When is payment due?
5. What is the governing law?
6. What is the launch schedule for a rocket?

## Notes

This web UI is meant to be a local demo and internal testing interface. The browser experience is intentionally simple and does not yet include authentication, user accounts, or production deployment safeguards.
