# Legal QA Chatbot: Standalone Integration Guide

The Legal QA Chatbot is packaged as a standalone, provider-decoupled backend service. Any external application (case management software, web portals, workflow engines, mobile apps) can integrate directly via the versioned REST API (`/api/v1`).

---

## 1. Overview & Architecture

```text
                 External Clients
      ┌──────────────────┴──────────────────┐
      │                                     │
Web Frontend (SPA)                    External Systems
(Existing UI)                 (Python, Node.js, cURL, etc.)
      │                                     │
      └──────────────────┬──────────────────┘
                         ▼
             FastAPI Gateway (/api/v1)
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
   Chat Service                    Document Service
        │                                 │
   Agent Orchestrator             Parser & Chunking
        │                                 │
        └────────────────┬────────────────┘
                         ▼
               RAGProvider Protocol
         ┌───────────────┴───────────────┐
         ▼                               ▼
  LocalRAGProvider                XAIRAGProvider
  (Qdrant + BM25 + RRF)         (Remote Collections)
         │                               │
         └───────────────┬───────────────┘
                         ▼
                LLMProvider Protocol
           (Gemini, OpenAI, xAI, Mock)
```

External consumers do not need to know about:
* Vector databases (Qdrant) or lexical indices (BM25)
* Reciprocal Rank Fusion (RRF) algorithms
* Internal chunking strategies or embeddings
* Provider-specific SDKs or credentials

All operations occur via stable HTTP endpoints with structured JSON responses.

---

## 2. API Endpoints Reference

Base URL: `http://localhost:8000/api/v1` (or your configured production host)

### 2.1 Health Check
* **Endpoint**: `GET /api/v1/health`
* **Response**:
```json
{
  "status": "ok",
  "app_name": "Legal Document QA Assistant",
  "environment": "development",
  "rag_provider": "local",
  "llm_provider": "gemini"
}
```

### 2.2 Upload Document
* **Endpoint**: `POST /api/v1/documents`
* **Content-Type**: `multipart/form-data`
* **Parameters**: `file` (binary PDF or supported image: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.tiff`)
* **Processing**: Synchronous. Documents are parsed, chunked, embedded, and indexed before the request returns.
* **Response** (`201 Created`):
```json
{
  "document_id": "doc_9111329e157f",
  "filename": "rental_agreement.pdf",
  "status": "processed",
  "page_count": 4,
  "chunk_count": 27,
  "content_hash": "45417202a0e99741a69ba57f8eec91074866264074dc468987ea36245baaab55",
  "created_at": "2026-10-08T12:55:00.000000"
}
```

### 2.3 List Documents
* **Endpoint**: `GET /api/v1/documents`
* **Response**:
```json
{
  "documents": [
    {
      "document_id": "doc_9111329e157f",
      "filename": "doc_9111329e157f_rental_agreement.pdf",
      "original_filename": "rental_agreement.pdf",
      "file_size_bytes": 43671,
      "page_count": 4,
      "chunk_count": 27,
      "content_hash": "45417202a0e99741a69ba57f8eec91074866264074dc468987ea36245baaab55",
      "status": "processed",
      "created_at": "2026-10-08T12:55:00.000000"
    }
  ],
  "total": 1
}
```

### 2.4 Get Document Details
* **Endpoint**: `GET /api/v1/documents/{document_id}`
* **Response**:
```json
{
  "document_id": "doc_9111329e157f",
  "filename": "doc_9111329e157f_rental_agreement.pdf",
  "original_filename": "rental_agreement.pdf",
  "file_size_bytes": 43671,
  "page_count": 4,
  "chunk_count": 27,
  "content_hash": "45417202a0e99741a69ba57f8eec91074866264074dc468987ea36245baaab55",
  "status": "processed",
  "created_at": "2026-10-08T12:55:00.000000"
}
```

### 2.5 Delete Document
* **Endpoint**: `DELETE /api/v1/documents/{document_id}`
* **Response**:
```json
{
  "success": true,
  "document_id": "doc_9111329e157f",
  "message": "Document and indexed vectors deleted successfully."
}
```

### 2.6 Ask Question / Chat
* **Endpoint**: `POST /api/v1/chat`
* **Content-Type**: `application/json`
* **Request Body**:
```json
{
  "question": "What is the notice period for terminating the agreement?",
  "document_id": "doc_9111329e157f",
  "conversation_id": "conv_128fb5e5b723406a",
  "top_k": 4
}
```
* **Response**:
```json
{
  "answer": "According to Clause 6 of the agreement, either party may terminate the tenancy by providing one month's written notice to the other party.",
  "conversation_id": "conv_128fb5e5b723406a",
  "document_id": "doc_9111329e157f",
  "sources": [
    {
      "document_id": "doc_9111329e157f",
      "chunk_id": "chk_c8508ab8ee39",
      "page_number": 2,
      "section": "Clause 6",
      "section_title": "Termination and Notice Period",
      "clause_number": "6",
      "text_snippet": "Either party may terminate this agreement by providing one (1) month's notice in writing...",
      "relevance_score": 0.372
    }
  ],
  "intent": "fact_extraction",
  "confidence": "high",
  "model": "gemini-3.8-flash",
  "disclaimer": "This analysis is generated by AI for informational purposes and does not constitute formal legal counsel."
}
```

### 2.7 Conversations
* **Create Session**: `POST /api/v1/conversations` (Body: `{"title": "Tenant Review", "document_id": "doc_xxx"}`)
* **List Sessions**: `GET /api/v1/conversations?limit=50&offset=0`
* **Get Details & History**: `GET /api/v1/conversations/{conversation_id}`
* **Delete Session**: `DELETE /api/v1/conversations/{conversation_id}`

---

## 3. Standard Error Envelope

When any error occurs, `/api/v1` returns consistent JSON with structured error codes:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document with ID 'doc_missing' not found.",
    "details": null
  }
}
```

Common Error Codes:
* `DOCUMENT_NOT_FOUND` (404)
* `CONVERSATION_NOT_FOUND` (404)
* `FILE_TOO_LARGE` (400)
* `UNSUPPORTED_MEDIA_TYPE` (400)
* `QUERY_TOO_LARGE` (400)
* `SCANNED_PDF_REJECTED` (422)
* `PROCESSING_ERROR` (500)

---

## 4. End-to-End Integration Code Examples

### 4.1 cURL
```bash
# 1. Health check
curl -s http://localhost:8000/api/v1/health

# 2. Upload document
DOC_RESP=$(curl -s -F "file=@documents/rental_agreement.pdf" http://localhost:8000/api/v1/documents)
DOC_ID=$(echo $DOC_RESP | jq -r .document_id)
echo "Uploaded Document ID: $DOC_ID"

# 3. Ask question
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "'"$DOC_ID"'",
    "question": "What is the notice period for termination?"
  }' | jq .

# 4. Clean up / delete document
curl -s -X DELETE http://localhost:8000/api/v1/documents/$DOC_ID | jq .
```

---

### 4.2 Python Integration Client
```python
import requests

BASE_URL = "http://localhost:8000/api/v1"

class LegalQAClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        r = requests.get(f"{self.base_url}/health")
        r.raise_for_status()
        return r.json()

    def upload_document(self, file_path: str) -> dict:
        with open(file_path, "rb") as f:
            files = {"file": f}
            r = requests.post(f"{self.base_url}/documents", files=files)
        r.raise_for_status()
        return r.json()

    def chat(self, question: str, document_id: str, conversation_id: str = None) -> dict:
        payload = {"question": question, "document_id": document_id}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        r = requests.post(f"{self.base_url}/chat", json=payload)
        r.raise_for_status()
        return r.json()

    def delete_document(self, document_id: str) -> dict:
        r = requests.delete(f"{self.base_url}/documents/{document_id}")
        r.raise_for_status()
        return r.json()

# Example workflow
if __name__ == "__main__":
    client = LegalQAClient()
    print("Health:", client.health())

    doc = client.upload_document("documents/rental_agreement.pdf")
    doc_id = doc["document_id"]
    print(f"Uploaded: {doc_id} ({doc['page_count']} pages, {doc['chunk_count']} chunks)")

    chat_res = client.chat(question="What is the notice period?", document_id=doc_id)
    print("Answer:", chat_res["answer"])
    for source in chat_res.get("sources", []):
        print(f"  - Page {source['page_number']} [{source.get('section', '')}]")

    client.delete_document(doc_id)
    print("Cleaned up document.")
```

---

### 4.3 JavaScript / TypeScript (Node.js & Browser Fetch)
```javascript
const BASE_URL = "http://localhost:8000/api/v1";

async function askLegalQuestion(filePath, question) {
  // 1. Upload Document
  const formData = new FormData();
  // In Node.js 18+: using fs/promises blob or Blob/File
  const fileBuffer = await require("fs").promises.readFile(filePath);
  const blob = new Blob([fileBuffer], { type: "application/pdf" });
  formData.append("file", blob, "agreement.pdf");

  const uploadRes = await fetch(`${BASE_URL}/documents`, {
    method: "POST",
    body: formData,
  });
  const uploadData = await uploadRes.json();
  const documentId = uploadData.document_id;
  console.log(`Document uploaded: ${documentId}`);

  // 2. Chat Query
  const chatRes = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: documentId,
      question: question,
      top_k: 4,
    }),
  });
  const chatData = await chatRes.json();
  console.log("Answer:", chatData.answer);
  console.log("Sources:", chatData.sources);

  // 3. Delete Document
  await fetch(`${BASE_URL}/documents/${documentId}`, {
    method: "DELETE",
  });
  console.log("Document cleaned up.");
}
```

---

## 5. Security & Deployment Best Practices

1. **Authentication**: Place the Legal QA Service behind an API Gateway (Kong, AWS API Gateway, NGINX) enforcing JWT / OAuth2 or API Keys before requests reach the service.
2. **CORS Configuration**: By default, `CORS_ALLOWED_ORIGINS` is set to `*`. In production, configure exact origins:
   ```bash
   CORS_ALLOWED_ORIGINS="https://app.yourdomain.com,https://dashboard.yourdomain.com"
   ```
3. **Document Isolation**: Multi-tenant systems should map tenant IDs to specific document IDs or use tenant-prefixed document IDs (`tenant123_doc_xxx`).
4. **Rate Limiting**: Apply token bucket or per-IP rate limits at your reverse proxy layer to protect retrieval and LLM token budgets.

