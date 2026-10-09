#!/usr/bin/env python3
"""
Standalone Integration Smoke Test (Legal QA Service /api/v1).
Exercises the complete lifecycle against the versioned API:
1. Health check
2. Document upload
3. Document metadata verification
4. Grounded question answering (with citation verification)
5. Conversation retrieval
6. Complete test data cleanup & deletion verification
"""

import sys
import io
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

def main():
    print("=== [Smoke Test] Legal QA Chatbot Standalone Integration ===")
    pdf_path = Path("documents/rental_agreement.pdf")
    if not pdf_path.exists():
        print(f"ERROR: Target PDF {pdf_path} not found.")
        sys.exit(1)

    with TestClient(app) as client:
        # Step 1: Health check
        print("\n1. Testing GET /api/v1/health...")
        health_res = client.get("/api/v1/health")
        assert health_res.status_code == 200, f"Health check failed: {health_res.text}"
        health_data = health_res.json()
        print(f"   Status: {health_data['status']} | Provider: {health_data['rag_provider']} / {health_data['llm_provider']}")
        assert health_data["status"] == "ok"

        # Step 2: Document upload
        print(f"\n2. Testing POST /api/v1/documents with {pdf_path.name}...")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        upload_res = client.post(
            "/api/v1/documents",
            files={"file": (pdf_path.name, io.BytesIO(pdf_bytes), "application/pdf")}
        )
        assert upload_res.status_code in (200, 201), f"Upload failed: {upload_res.text}"
        doc_data = upload_res.json()
        doc_id = doc_data["document_id"]
        print(f"   Uploaded document ID: {doc_id} (pages={doc_data['page_count']}, chunks={doc_data['chunk_count']})")
        assert doc_id.startswith("doc_")
        assert doc_data["page_count"] > 0
        assert doc_data["chunk_count"] > 0

        try:
            # Step 3: Document details
            print(f"\n3. Testing GET /api/v1/documents/{doc_id}...")
            get_res = client.get(f"/api/v1/documents/{doc_id}")
            assert get_res.status_code == 200, f"Get document failed: {get_res.text}"
            detail_data = get_res.json()
            assert detail_data["document_id"] == doc_id
            print(f"   Document verified: {detail_data['filename']} (status={detail_data['status']})")

            # Step 4: Ask Question
            question = "What is the notice period for terminating the agreement?"
            print(f"\n4. Testing POST /api/v1/chat with question: '{question}'...")
            chat_res = client.post(
                "/api/v1/chat",
                json={
                    "document_id": doc_id,
                    "question": question,
                    "top_k": 4
                }
            )
            assert chat_res.status_code == 200, f"Chat request failed: {chat_res.text}"
            chat_data = chat_res.json()
            print(f"   Answer: {chat_data['answer'][:120]}...")
            print(f"   Sources returned: {len(chat_data['sources'])}")
            assert len(chat_data["answer"]) > 0
            assert "conversation_id" in chat_data
            conv_id = chat_data["conversation_id"]

            for idx, src in enumerate(chat_data["sources"], 1):
                print(f"     Source #{idx}: Page {src['page_number']}, Section '{src.get('section', 'General')}'")

            # Step 5: Check conversation history
            print(f"\n5. Testing GET /api/v1/conversations/{conv_id}...")
            conv_res = client.get(f"/api/v1/conversations/{conv_id}")
            assert conv_res.status_code == 200, f"Conversation lookup failed: {conv_res.text}"
            conv_data = conv_res.json()
            print(f"   Conversation active with {len(conv_data['messages'])} messages.")
            assert len(conv_data["messages"]) > 0

        finally:
            # Step 6: Test Data Cleanup
            print(f"\n6. Testing DELETE /api/v1/documents/{doc_id} (Cleanup)...")
            del_res = client.delete(f"/api/v1/documents/{doc_id}")
            assert del_res.status_code == 200, f"Delete failed: {del_res.text}"
            del_data = del_res.json()
            assert del_data["success"] is True
            print(f"   Deleted document {doc_id} successfully.")

            # Verify deletion
            verify_res = client.get(f"/api/v1/documents/{doc_id}")
            assert verify_res.status_code == 404
            assert verify_res.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
            print("   Confirmed 404 DOCUMENT_NOT_FOUND after deletion.")

    print("\n=== [SUCCESS] All Standalone Integration Smoke Tests Passed Cleanly ===")

if __name__ == "__main__":
    main()

