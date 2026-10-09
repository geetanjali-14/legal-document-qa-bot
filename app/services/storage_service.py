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


class CloudflareR2StorageService(StorageService):
    """
    Cloudflare R2 storage backend using standard boto3 S3 client interface.
    Maintains a local temporary/cache directory for processing needs (PyMuPDF / PIL).
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        local_cache_dir: Optional[Path] = None,
        s3_client: Optional[object] = None
    ):
        self.account_id = account_id or settings.R2_ACCOUNT_ID
        self.access_key_id = access_key_id or settings.R2_ACCESS_KEY_ID
        self.secret_access_key = secret_access_key or settings.R2_SECRET_ACCESS_KEY
        self.bucket_name = bucket_name or settings.R2_BUCKET_NAME
        self.endpoint_url = (
            endpoint_url
            or settings.R2_ENDPOINT_URL
            or (f"https://{self.account_id}.r2.cloudflarestorage.com" if self.account_id else "")
        )
        self.local_cache_dir = Path(local_cache_dir) if local_cache_dir else settings.UPLOAD_DIR
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)

        if s3_client is not None:
            self._client = s3_client
        else:
            self._client = self._init_client()

    def _init_client(self):
        try:
            import boto3
            from botocore.config import Config
            return boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(signature_version="s3v4"),
                region_name="auto"
            )
        except Exception as e:
            logger.error(f"Failed to initialize boto3 R2 S3 client: {e}")
            raise RuntimeError(f"Cloudflare R2 initialization failed: {e}") from e

    def save_file(self, filename: str, content: bytes) -> str:
        # Cache locally
        local_path = self.local_cache_dir / filename
        local_path.write_bytes(content)

        # Upload to R2 bucket
        try:
            self._client.put_object(
                Bucket=self.bucket_name,
                Key=filename,
                Body=content
            )
            logger.info(f"Uploaded file '{filename}' to Cloudflare R2 bucket '{self.bucket_name}'")
        except Exception as e:
            logger.error(f"Failed to upload '{filename}' to Cloudflare R2: {e}")
            raise RuntimeError(f"Cloudflare R2 upload error: {e}") from e
        return filename

    def get_file_bytes(self, filename: str) -> Optional[bytes]:
        # Return from local cache if present
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            return local_path.read_bytes()

        # Fetch from R2 bucket
        try:
            response = self._client.get_object(Bucket=self.bucket_name, Key=filename)
            content = response["Body"].read()
            # Cache locally
            local_path.write_bytes(content)
            return content
        except Exception as e:
            logger.warning(f"Could not retrieve '{filename}' from Cloudflare R2: {e}")
            return None

    def file_exists(self, filename: str) -> bool:
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            return True
        try:
            self._client.head_object(Bucket=self.bucket_name, Key=filename)
            return True
        except Exception:
            return False

    def delete_file(self, filename: str) -> bool:
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            local_path.unlink()

        try:
            self._client.delete_object(Bucket=self.bucket_name, Key=filename)
            logger.info(f"Deleted file '{filename}' from Cloudflare R2 bucket '{self.bucket_name}'")
            return True
        except Exception as e:
            logger.warning(f"Could not delete '{filename}' from Cloudflare R2: {e}")
            return False

    def get_local_path(self, filename: str) -> Optional[Path]:
        local_path = self.local_cache_dir / filename
        if local_path.exists():
            return local_path

        # If not cached locally, download from R2
        content = self.get_file_bytes(filename)
        if content is not None:
            return local_path
        return None


def get_storage_service(backend: Optional[str] = None) -> StorageService:
    """Factory helper to obtain the configured storage service."""
    chosen_backend = (backend or settings.STORAGE_BACKEND).lower()
    if chosen_backend == "r2":
        return CloudflareR2StorageService()
    return LocalStorageService()

