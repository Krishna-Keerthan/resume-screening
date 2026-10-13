"""
app/services/storage_service.py

Abstracted file storage backend for resume files.

Interface (both backends):
    upload(file_bytes, ext)  -> StorageResult      stored under a random key
    delete(key)              -> None
    download_bytes(key)      -> bytes

Cloudinary only:
    signed_url(key, ttl)     -> short-lived download URL

A storage key is generated here from a random UUID and the validated
extension. The user's filename never reaches storage. Files are private in
both backends: Cloudinary uploads use type="authenticated", and the local
backend's files are never served statically (the download route streams
them after an ownership check).

Backend is selected via STORAGE_PROVIDER config:
    local      — writes to UPLOAD_FOLDER on disk (dev / testing)
    cloudinary — uploads to Cloudinary as authenticated raw files (prod)

Usage (in upload_resume route):
    storage = StorageService.from_config(current_app.config)
    result  = storage.upload(file_bytes, ext)
    # result.key → stored in Resume.storage_key (the source of truth)
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class StorageResult:
    """Unified result returned by any storage backend's upload()."""
    key:      str   # Cloudinary public_id, or a path relative to UPLOAD_FOLDER
    size_kb:  int   # File size rounded to nearest KB (minimum 1)
    provider: str   # "cloudinary" | "local"


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

            missing = [
                key for key, value in (
                    ("CLOUDINARY_CLOUD_NAME", cloud_name),
                    ("CLOUDINARY_API_KEY",    api_key),
                    ("CLOUDINARY_API_SECRET", api_secret),
                )
                if not value
            ]
            if missing:
                raise StorageError(
                    "STORAGE_PROVIDER=cloudinary but these settings are empty: "
                    + ", ".join(missing)
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


def _random_key(ext: str) -> str:
    """`<32 hex>.<ext>`, with the extension reduced to lowercase letters and digits."""
    clean = re.sub(r"[^a-z0-9]", "", ext.lower())[:10]
    return f"{uuid.uuid4().hex}.{clean}" if clean else uuid.uuid4().hex


# ─────────────────────────────────────────────────────────────────────────────
# Local backend
# ─────────────────────────────────────────────────────────────────────────────

class LocalStorageBackend:
    """
    Local filesystem backend (development and testing).

    A key is a path relative to UPLOAD_FOLDER. Keys that resolve outside
    that folder are refused.
    """

    provider = "local"

    def __init__(self, upload_dir: str):
        self._root = Path(upload_dir).resolve()

    def _path(self, key: str) -> Path:
        if not key:
            raise StorageError("Empty storage key.")
        path = (self._root / key).resolve()
        if path != self._root and self._root not in path.parents:
            raise StorageError("Storage key is outside the upload folder.")
        return path

    def upload(self, file_bytes: bytes, ext: str) -> StorageResult:
        """Write bytes under a random key and return it."""
        key = _random_key(ext)
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file_bytes)
        except OSError as exc:
            raise StorageError(f"Failed to write file to disk: {exc}") from exc

        size_kb = max(1, round(len(file_bytes) / 1024))
        logger.info("Local upload saved", extra={"key": key, "size_kb": size_kb})
        return StorageResult(key=key, size_kb=size_kb, provider="local")

    def delete(self, key: str) -> None:
        """Delete the file at key. Silently ignores missing files and bad keys."""
        try:
            path = self._path(key)
            if path.is_file():
                path.unlink()
                logger.info("Local file deleted", extra={"key": key})
        except (OSError, StorageError) as exc:
            logger.warning("Failed to delete local file %s: %s", key, exc)

    def download_bytes(self, key: str) -> bytes:
        """Read the file at key."""
        path = self._path(key)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise StorageError(f"Cannot read stored file '{key}': {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Cloudinary backend
# ─────────────────────────────────────────────────────────────────────────────

class CloudinaryStorageBackend:
    """
    Cloudinary storage backend.

    Files are uploaded as resource_type="raw", type="authenticated": they
    have no public URL, and every download goes through a signed, expiring
    URL. The key is the Cloudinary public_id, which includes the extension.
    """

    provider = "cloudinary"

    def __init__(self, cloud_name: str, api_key: str, api_secret: str, folder: str = "resumes"):
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
                "cloudinary package is not installed. Run: pip install cloudinary"
            ) from exc

    def upload(self, file_bytes: bytes, ext: str) -> StorageResult:
        """Upload bytes as an authenticated raw file under a random public_id."""
        try:
            import cloudinary.uploader
        except ImportError as exc:
            raise StorageError("cloudinary package is not installed.") from exc

        public_id = _random_key(ext)
        try:
            response = cloudinary.uploader.upload(
                file_bytes,
                resource_type="raw",
                type="authenticated",
                folder=self._folder,
                public_id=public_id,
                use_filename=False,
                unique_filename=False,
                overwrite=False,
                tags=["resume"],
            )
        except Exception as exc:
            logger.error("Cloudinary upload failed", exc_info=True)
            raise StorageError(f"Cloudinary upload failed: {exc}") from exc

        key = response.get("public_id") or f"{self._folder}/{public_id}"
        size_kb = max(1, round(response.get("bytes", len(file_bytes)) / 1024))
        logger.info("Cloudinary upload complete", extra={"key": key, "size_kb": size_kb})
        return StorageResult(key=key, size_kb=size_kb, provider="cloudinary")

    def delete(self, key: str) -> None:
        """Delete an authenticated raw file; best-effort, failures are logged."""
        if not key:
            return
        try:
            import cloudinary.uploader
            result = cloudinary.uploader.destroy(key, resource_type="raw", type="authenticated")
            if result.get("result") not in ("ok", "not found"):
                logger.warning(
                    "Cloudinary delete returned unexpected result",
                    extra={"key": key, "result": result},
                )
            else:
                logger.info("Cloudinary file deleted", extra={"key": key})
        except Exception as exc:
            logger.warning("Failed to delete Cloudinary file %s: %s", key, exc)

    def signed_url(self, key: str, ttl: int) -> str:
        """A download URL for key that Cloudinary stops honouring after ttl seconds."""
        try:
            import cloudinary.utils
            return cloudinary.utils.private_download_url(
                key,
                "",
                resource_type="raw",
                type="authenticated",
                expires_at=int(time.time()) + ttl,
            )
        except Exception as exc:
            raise StorageError(f"Failed to sign a download URL: {exc}") from exc

    def download_bytes(self, key: str) -> bytes:
        """Fetch the file through a short-lived signed URL."""
        url = self.signed_url(key, ttl=60)
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
        except Exception as exc:
            raise StorageError(f"Failed to download stored file '{key}': {exc}") from exc
        if not data:
            raise StorageError(f"Downloaded 0 bytes for '{key}'.")
        return data
