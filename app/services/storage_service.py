from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, BinaryIO
import io
import os
from app.core.config import settings
from app.core.logging import logger


class StorageService(ABC):
    """
    Abstract interface for document file storage.
    Enables local file system storage for development/demo and
    Cloudflare R2 (S3-compatible) object storage for production persistence.
    """

    @abstractmethod
    def save_file(self, filename: str, content: bytes) -> str:
        """Save file content and return the stored identifier or relative key."""
        pass

    @abstractmethod
    def get_file_bytes(self, filename: str) -> Optional[bytes]:
        """Retrieve file content bytes. Returns None if file does not exist."""
        pass

    @abstractmethod
    def file_exists(self, filename: str) -> bool:
        """Check if file exists in the storage backend."""
        pass

    @abstractmethod
    def delete_file(self, filename: str) -> bool:
        """Delete file from storage. Returns True if removed, False otherwise."""
        pass

    @abstractmethod
    def get_local_path(self, filename: str) -> Optional[Path]:
        """
        Returns a local filesystem Path if available or cached locally.
        Useful for libraries that require a filesystem path (e.g. PyMuPDF / PIL).
        """
        pass


class LocalStorageService(StorageService):
    """Local filesystem storage backend."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else settings.UPLOAD_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_file(self, filename: str, content: bytes) -> str:
        target = self.base_dir / filename
        target.write_bytes(content)
        return filename

    def get_file_bytes(self, filename: str) -> Optional[bytes]:
        target = self.base_dir / filename
        if not target.exists():
            return None
        return target.read_bytes()

    def file_exists(self, filename: str) -> bool:
        return (self.base_dir / filename).exists()

    def delete_file(self, filename: str) -> bool:
        target = self.base_dir / filename
        if target.exists():
            target.unlink()
            return True
        return False

    def get_local_path(self, filename: str) -> Optional[Path]:
        target = self.base_dir / filename
        return target if target.exists() else None


class SupabaseStorageService(StorageService):
    """
    Supabase Storage backend using standard Supabase Storage REST API (v1).
    Maintains a local cache directory for fast processing needs (PyMuPDF / PIL).
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        service_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        local_cache_dir: Optional[Path] = None,
        http_client: Optional[object] = None
    ):
        raw_url = supabase_url or settings.SUPABASE_URL
        self.supabase_url = raw_url.rstrip("/") if raw_url else ""
        self.service_key = service_key or settings.SUPABASE_SERVICE_KEY
        self.bucket_name = bucket_name or settings.SUPABASE_BUCKET_NAME
        self.local_cache_dir = Path(local_cache_dir) if local_cache_dir else settings.UPLOAD_DIR
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)

        import httpx
        self._client = http_client or httpx.Client(timeout=30.0)

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.service_key}",
            "apikey": self.service_key,
        }

    def _object_url(self, filename: str) -> str:
        # Supabase Storage endpoint: /storage/v1/object/{bucket}/{wildcard}
        return f"{self.supabase_url}/storage/v1/object/{self.bucket_name}/{filename}"

    def save_file(self, filename: str, content: bytes) -> str:
        # Cache locally
        local_path = self.local_cache_dir / filename
        local_path.write_bytes(content)

        if not self.supabase_url or not self.service_key:
            logger.info(f"Supabase credentials not configured; stored '{filename}' in local cache only.")
            return filename

        try:
            url = self._object_url(filename)
            headers = {**self._headers, "Content-Type": "application/octet-stream", "x-upsert": "true"}
            resp = self._client.post(url, content=content, headers=headers)
            if resp.status_code not in (200, 201):
                # Try PUT if POST returned 400 (duplicate / update)
                resp = self._client.put(url, content=content, headers=headers)
            resp.raise_for_status()
            logger.info(f"Uploaded file '{filename}' to Supabase bucket '{self.bucket_name}'")
        except Exception as e:
            logger.error(f"Failed to upload '{filename}' to Supabase Storage: {e}")
            raise RuntimeError(f"Supabase Storage upload error: {e}") from e
        return filename

    def get_file_bytes(self, filename: str) -> Optional[bytes]:
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            return local_path.read_bytes()

        if not self.supabase_url or not self.service_key:
            return None

        try:
            url = self._object_url(filename)
            resp = self._client.get(url, headers=self._headers)
            if resp.status_code == 200:
                content = resp.content
                local_path.write_bytes(content)
                return content
            elif resp.status_code == 404:
                return None
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Could not retrieve '{filename}' from Supabase Storage: {e}")
            return None
        return None

    def file_exists(self, filename: str) -> bool:
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            return True

        if not self.supabase_url or not self.service_key:
            return False

        try:
            url = self._object_url(filename)
            # Use GET or HEAD to test object presence
            resp = self._client.get(url, headers=self._headers)
            return resp.status_code == 200
        except Exception:
            return False

    def delete_file(self, filename: str) -> bool:
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            local_path.unlink()

        if not self.supabase_url or not self.service_key:
            return True

        try:
            url = self._object_url(filename)
            resp = self._client.delete(url, headers=self._headers)
            if resp.status_code in (200, 204):
                logger.info(f"Deleted file '{filename}' from Supabase Storage bucket '{self.bucket_name}'")
                return True
            return False
        except Exception as e:
            logger.warning(f"Could not delete '{filename}' from Supabase Storage: {e}")
            return False

    def get_local_path(self, filename: str) -> Optional[Path]:
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            return local_path

        content = self.get_file_bytes(filename)
        if content is not None:
            return local_path
        return None


def get_storage_service(backend: Optional[str] = None) -> StorageService:
    """Factory helper to obtain the configured storage service."""
    chosen_backend = (backend or settings.STORAGE_BACKEND).lower()
    if chosen_backend == "supabase":
        return SupabaseStorageService()
    return LocalStorageService()

