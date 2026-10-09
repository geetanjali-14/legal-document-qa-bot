import httpx
from typing import Optional, Dict, Any, List
from app.core.config import settings
from app.core.logging import logger


class LegalQAAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class LegalQAClient:
    """
    HTTP Client interacting with the existing Legal QA Assistant FastAPI REST API (/api/v1).
    Encapsulates connection timeouts, structured error handling, and clean JSON payloads.
    """

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 45.0):
        url = base_url or settings.LEGAL_QA_API_BASE_URL or "http://localhost:8000/api/v1"
        self.base_url = url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds, connect=10.0)

    def health(self) -> Dict[str, Any]:
        """Check API health."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(f"{self.base_url}/health")
                res.raise_for_status()
                return res.json()
        except httpx.ConnectError:
            raise LegalQAAPIError("Cannot reach the Legal QA service. Please ensure the backend is running.")
        except httpx.HTTPStatusError as e:
            raise LegalQAAPIError(f"Health check failed with status {e.response.status_code}", status_code=e.response.status_code)
        except Exception as e:
            raise LegalQAAPIError(f"Health check error: {str(e)}")

    def chat(
        self,
        question: str,
        document_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        top_k: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calls POST /api/v1/chat to get grounded answers and source citations.
        """
        payload = {"question": question}
        if document_id:
            payload["document_id"] = document_id
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if top_k:
            payload["top_k"] = top_k

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(f"{self.base_url}/chat", json=payload)
                if res.status_code != 200:
                    self._handle_error_response(res)
                return res.json()
        except httpx.ConnectError:
            raise LegalQAAPIError("The Legal QA service is currently unreachable. Please try again shortly.")
        except httpx.TimeoutException:
            raise LegalQAAPIError("The query took longer than expected to process. Please try a simpler question.")
        except LegalQAAPIError:
            raise
        except Exception as e:
            logger.error(f"[LegalQAClient] Unexpected error calling chat: {e}")
            raise LegalQAAPIError("An unexpected error occurred while communicating with the QA service.")

    def list_documents(self) -> List[Dict[str, Any]]:
        """Calls GET /api/v1/documents to list processed documents."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(f"{self.base_url}/documents")
                if res.status_code != 200:
                    self._handle_error_response(res)
                data = res.json()
                return data.get("documents", [])
        except httpx.ConnectError:
            raise LegalQAAPIError("The Legal QA service is unreachable.")
        except LegalQAAPIError:
            raise
        except Exception as e:
            logger.error(f"[LegalQAClient] Error listing documents: {e}")
            raise LegalQAAPIError("Could not retrieve documents from the QA service.")

    def get_document(self, document_id: str) -> Dict[str, Any]:
        """Calls GET /api/v1/documents/{document_id}."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(f"{self.base_url}/documents/{document_id}")
                if res.status_code != 200:
                    self._handle_error_response(res)
                return res.json()
        except httpx.ConnectError:
            raise LegalQAAPIError("The Legal QA service is unreachable.")
        except LegalQAAPIError:
            raise
        except Exception as e:
            logger.error(f"[LegalQAClient] Error retrieving document {document_id}: {e}")
            raise LegalQAAPIError(f"Could not retrieve document '{document_id}'.")

    def upload_document(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """
        Calls POST /api/v1/documents to upload and index a PDF file.
        """
        files = {"file": (filename, file_bytes, "application/pdf")}
        try:
            # Document ingestion can take longer due to chunking & embeddings
            upload_timeout = httpx.Timeout(120.0, connect=10.0)
            with httpx.Client(timeout=upload_timeout) as client:
                res = client.post(f"{self.base_url}/documents", files=files)
                if res.status_code not in (200, 201):
                    self._handle_error_response(res)
                return res.json()
        except httpx.ConnectError:
            raise LegalQAAPIError("The Legal QA service is unreachable.")
        except httpx.TimeoutException:
            raise LegalQAAPIError("The document upload timed out during processing.")
        except LegalQAAPIError:
            raise
        except Exception as e:
            logger.error(f"[LegalQAClient] Error uploading document {filename}: {e}")
            raise LegalQAAPIError(f"Failed to upload document '{filename}'.")

    def _handle_error_response(self, response: httpx.Response):
        """Parse structured error from v1 API without leaking internal details."""
        try:
            body = response.json()
            err = body.get("error", {})
            err_code = err.get("code", "UNKNOWN_ERROR")
            err_msg = err.get("message", "An error occurred.")
            raise LegalQAAPIError(err_msg, status_code=response.status_code, error_code=err_code)
        except (ValueError, KeyError):
            raise LegalQAAPIError(
                f"Service returned error code {response.status_code}.",
                status_code=response.status_code
            )

