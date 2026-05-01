"""
app/services/storage_service.py

Abstracted file storage backend.

Provides a unified interface for storing and deleting resume files,
regardless of whether the backend is local disk (dev) or Cloudinary (prod).

Interface:
    upload(file_bytes, filename, folder) -> StorageResult
    delete(public_key)                   -> None
    download_bytes(url)                  -> bytes

Backend is selected via STORAGE_PROVIDER config:
    local      — writes to UPLOAD_FOLDER on disk (dev / testing)
    cloudinary — uploads to Cloudinary using resource_type="raw" (prod)

Usage (in upload_resume route):
    storage = StorageService.from_config(current_app.config)
    result  = storage.upload(file_bytes, file.filename)
    # result.url        → stored in Resume.file_path (Cloudinary secure_url or local path)
    # result.public_key → stored in Resume.storage_key (Cloudinary public_id or local path)
    # result.size_kb    → stored in Resume.file_size_kb
"""

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StorageResult:
    """Unified result returned by any storage backend's upload()."""
    url:        str   # Publicly accessible URL (or local absolute path for local backend)
    public_key: str   # Deletion handle — Cloudinary public_id or local file path
    size_kb:    int   # File size rounded to nearest KB (minimum 1)
    provider:   str   # "cloudinary" | "local"


class StorageError(Exception):
    """Raised when any storage operation fails."""


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

class StorageService:
    """
    Factory + public interface.

    Do not instantiate directly — use StorageService.from_config(app.config).
    """

    @staticmethod
    def from_config(config) -> "LocalStorageBackend | CloudinaryStorageBackend":
        """
        Instantiate the correct backend from Flask config.

        Args:
            config: Flask config dict or object.

        Returns:
            LocalStorageBackend or CloudinaryStorageBackend instance.
        """
        def cfg(key, default=None):
            if isinstance(config, dict):
                return config.get(key, default)
            return getattr(config, key, default)

        provider = (cfg("STORAGE_PROVIDER") or "local").lower().strip()

        if provider == "cloudinary":
            cloud_name = cfg("CLOUDINARY_CLOUD_NAME", "")
            api_key    = cfg("CLOUDINARY_API_KEY", "")
            api_secret = cfg("CLOUDINARY_API_SECRET", "")

            if not all([cloud_name, api_key, api_secret]):
                logger.warning(
                    "STORAGE_PROVIDER=cloudinary but Cloudinary credentials are incomplete. "
                    "Falling back to local storage."
                )
                return LocalStorageBackend(
                    upload_dir=cfg("UPLOAD_FOLDER", "/tmp/uploads"),
                )

            return CloudinaryStorageBackend(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                folder=cfg("CLOUDINARY_FOLDER", "resumes"),
            )

        # Default: local
        return LocalStorageBackend(
            upload_dir=cfg("UPLOAD_FOLDER", "/tmp/uploads"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Local backend
# ─────────────────────────────────────────────────────────────────────────────

class LocalStorageBackend:
    """
    Local filesystem backend.

    Used in development and testing. Files are written to UPLOAD_FOLDER.
    `url` and `public_key` are both the absolute file path.
    """

    provider = "local"

    def __init__(self, upload_dir: str):
        self._upload_dir = upload_dir

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        folder: str = "",
    ) -> StorageResult:
        """
        Write bytes to disk under a UUID-prefixed filename.

        Args:
            file_bytes: Raw file content.
            filename:   Original filename (used for extension only).
            folder:     Subdirectory under upload_dir (optional).

        Returns:
            StorageResult with url = public_key = absolute path.
        """
        ext       = Path(filename).suffix.lower()
        unique    = f"{uuid.uuid4().hex}{ext}"
        target_dir = os.path.join(self._upload_dir, folder) if folder else self._upload_dir

        try:
            Path(target_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"Cannot create upload directory '{target_dir}': {exc}") from exc

        file_path = os.path.join(target_dir, unique)
        try:
            with open(file_path, "wb") as fh:
                fh.write(file_bytes)
        except OSError as exc:
            raise StorageError(f"Failed to write file to disk: {exc}") from exc

        size_kb = max(1, round(len(file_bytes) / 1024))
        logger.info("Local upload saved", extra={"path": file_path, "size_kb": size_kb})

        return StorageResult(
            url=file_path,
            public_key=file_path,
            size_kb=size_kb,
            provider="local",
        )

    def delete(self, public_key: str) -> None:
        """Delete file at public_key path. Silently ignores missing files."""
        try:
            if public_key and os.path.exists(public_key):
                os.remove(public_key)
                logger.info("Local file deleted", extra={"path": public_key})
        except OSError as exc:
            logger.warning("Failed to delete local file %s: %s", public_key, exc)

    def download_bytes(self, url: str) -> bytes:
        """Read file from local path and return raw bytes."""
        try:
            with open(url, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise StorageError(f"Cannot read local file '{url}': {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Cloudinary backend
# ─────────────────────────────────────────────────────────────────────────────

class CloudinaryStorageBackend:
    """
    Cloudinary storage backend.

    Uploads resumes as raw files (resource_type="raw") so PDF/DOCX are
    stored and served as-is without image conversion.

    public_key = Cloudinary public_id  (used for deletion)
    url        = Cloudinary secure_url (used for download + re-parse)
    """

    provider = "cloudinary"

    def __init__(
        self,
        cloud_name: str,
        api_key: str,
        api_secret: str,
        folder: str = "resumes",
    ):
        self._folder = folder
        self._configure(cloud_name, api_key, api_secret)

    def _configure(self, cloud_name: str, api_key: str, api_secret: str) -> None:
        try:
            import cloudinary
            cloudinary.config(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                secure=True,
            )
        except ImportError as exc:
            raise StorageError(
                "cloudinary package is not installed. "
                "Run: pip install cloudinary"
            ) from exc

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        folder: str = "",
    ) -> StorageResult:
        """
        Upload raw bytes to Cloudinary.

        IMPORTANT: resource_type="raw" is required for PDF and DOCX.
        Using the default ("image") will cause Cloudinary to attempt
        image conversion and fail or produce an unusable URL.

        Args:
            file_bytes: Raw file content.
            filename:   Original filename — used to derive the public_id suffix.
            folder:     Cloudinary folder override (defaults to self._folder).

        Returns:
            StorageResult with Cloudinary secure_url and public_id.
        """
        try:
            import cloudinary.uploader
        except ImportError as exc:
            raise StorageError("cloudinary package is not installed.") from exc

        ext        = Path(filename).suffix.lower()
        public_id  = f"{uuid.uuid4().hex}"
        target_folder = folder or self._folder

        try:
            response = cloudinary.uploader.upload(
                file_bytes,
                resource_type="raw",       # CRITICAL: raw for PDF/DOCX
                folder=target_folder,
                public_id=public_id,
                use_filename=False,        # use our generated public_id
                overwrite=False,
                tags=["resume"],
            )
        except Exception as exc:
            logger.error("Cloudinary upload failed", exc_info=True)
            raise StorageError(f"Cloudinary upload failed: {exc}") from exc

        secure_url    = response.get("secure_url", "")
        full_public_id = response.get("public_id", f"{target_folder}/{public_id}")
        size_bytes    = response.get("bytes", len(file_bytes))
        size_kb       = max(1, round(size_bytes / 1024))

        logger.info(
            "Cloudinary upload complete",
            extra={"public_id": full_public_id, "size_kb": size_kb},
        )

        return StorageResult(
            url=secure_url,
            public_key=full_public_id,
            size_kb=size_kb,
            provider="cloudinary",
        )

    def delete(self, public_key: str) -> None:
        """
        Delete a file from Cloudinary by its public_id.

        Must pass resource_type="raw" — same type used during upload.
        """
        if not public_key:
            return
        try:
            import cloudinary.uploader
            result = cloudinary.uploader.destroy(public_key, resource_type="raw")
            if result.get("result") not in ("ok", "not found"):
                logger.warning(
                    "Cloudinary delete returned unexpected result",
                    extra={"public_key": public_key, "result": result},
                )
            else:
                logger.info("Cloudinary file deleted", extra={"public_key": public_key})
        except Exception as exc:
            logger.warning(
                "Failed to delete Cloudinary file %s: %s", public_key, exc
            )

    def download_bytes(self, url: str) -> bytes:
        """
        Download a file from Cloudinary secure_url and return raw bytes.

        Used by analyze_resume() when force_reparse=True — the file is no
        longer on local disk so it must be fetched from Cloudinary.
        """
        try:
            import urllib.request
            import urllib.error
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            if not data:
                raise StorageError(f"Downloaded 0 bytes from '{url}'.")
            return data
        except Exception as exc:
            raise StorageError(f"Failed to download file from '{url}': {exc}") from exc