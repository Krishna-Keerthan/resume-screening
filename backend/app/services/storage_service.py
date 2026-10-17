"""
app/services/storage_service.py

File storage for resume files, behind one interface.

Interface (StorageBackend, every backend):
    provider                 -> its name, for logging and the upload response only
    upload(file_bytes, ext)  -> StorageResult      stored under a random key
    download_bytes(key)      -> bytes              StorageNotFound if there is no such object
    delete(key)              -> None               never raises
    signed_url(key, ttl)     -> str | None         a download URL that stops working after
                                                   ttl seconds, or None when the backend has
                                                   no direct URL (the route then serves the
                                                   bytes itself, after its ownership check)

A storage key is generated here from a random UUID and the validated extension. The
user's filename never reaches storage. Files are private in every backend: they have no
public URL, and the local backend's files are never served statically.

The backend is chosen by STORAGE_PROVIDER, in exactly one place: StorageService.from_config
looks the name up in _BUILDERS. Nothing else in the application branches on the provider.
To add a backend, write the class and add one builder to _BUILDERS.

Usage (in upload_resume route):
    storage = StorageService.from_config(current_app.config)
    result  = storage.upload(file_bytes, ext)
    # result.key -> stored in Resume.storage_key (the source of truth)
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import quote, urlsplit

import httpx

logger = logging.getLogger(__name__)


@dataclass
class StorageResult:
    """Unified result returned by any storage backend's upload()."""
    key:      str   # the object's key in the store (a path relative to UPLOAD_FOLDER, locally)
    size_kb:  int   # File size rounded to nearest KB (minimum 1)
    provider: str   # the backend's name, e.g. "local"


class StorageError(Exception):
    """Raised when any storage operation fails."""


class StorageNotFound(StorageError):
    """The store has no object under the key (as opposed to the store being unreachable)."""


class StorageBackend(Protocol):
    provider: str

    def upload(self, file_bytes: bytes, ext: str) -> StorageResult: ...
    def download_bytes(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, ttl: int) -> str | None: ...


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

class StorageService:
    """
    Factory. Do not instantiate directly: use StorageService.from_config(app.config).
    """

    @staticmethod
    def from_config(config) -> StorageBackend:
        """
        Build the backend named by STORAGE_PROVIDER (default "local").

        Raises StorageError for an unknown provider, so a typo stops startup instead of
        quietly writing uploads to local disk, and for a provider whose settings are
        incomplete.
        """
        def cfg(key, default=None):
            if isinstance(config, dict):
                return config.get(key, default)
            return getattr(config, key, default)

        provider = ((cfg("STORAGE_PROVIDER") or "").strip().lower()) or "local"
        builder = _BUILDERS.get(provider)
        if builder is None:
            raise StorageError(
                f"Unknown STORAGE_PROVIDER '{provider}'. Valid values: {', '.join(sorted(_BUILDERS))}."
            )
        return builder(cfg)


def _build_local(cfg: Callable) -> "LocalStorageBackend":
    return LocalStorageBackend(upload_dir=cfg("UPLOAD_FOLDER", "/tmp/uploads"))


def _build_cloudinary(cfg: Callable) -> "CloudinaryStorageBackend":
    values = {
        "CLOUDINARY_CLOUD_NAME": cfg("CLOUDINARY_CLOUD_NAME", ""),
        "CLOUDINARY_API_KEY":    cfg("CLOUDINARY_API_KEY", ""),
        "CLOUDINARY_API_SECRET": cfg("CLOUDINARY_API_SECRET", ""),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise StorageError(
            "STORAGE_PROVIDER=cloudinary but these settings are empty: " + ", ".join(missing)
        )
    return CloudinaryStorageBackend(
        cloud_name=values["CLOUDINARY_CLOUD_NAME"],
        api_key=values["CLOUDINARY_API_KEY"],
        api_secret=values["CLOUDINARY_API_SECRET"],
        folder=cfg("CLOUDINARY_FOLDER", "resumes"),
    )


def _build_supabase(cfg: Callable) -> "SupabaseStorageBackend":
    values = {
        "SUPABASE_URL":              cfg("SUPABASE_URL", ""),
        "SUPABASE_SERVICE_ROLE_KEY": cfg("SUPABASE_SERVICE_ROLE_KEY", ""),
        "SUPABASE_BUCKET":           cfg("SUPABASE_BUCKET", ""),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise StorageError(
            "STORAGE_PROVIDER=supabase but these settings are empty: " + ", ".join(missing)
        )
    parts = urlsplit(values["SUPABASE_URL"])
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/"):
        raise StorageError(
            "SUPABASE_URL must be the project's base URL, for example https://<project>.supabase.co "
            "(http or https, no path: the backend adds /storage/v1 itself)."
        )
    return SupabaseStorageBackend(
        url=values["SUPABASE_URL"],
        service_role_key=values["SUPABASE_SERVICE_ROLE_KEY"],
        bucket=values["SUPABASE_BUCKET"],
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
        except FileNotFoundError as exc:
            raise StorageNotFound(f"No stored file '{key}'.") from exc
        except OSError as exc:
            raise StorageError(f"Cannot read stored file '{key}': {exc}") from exc

    def signed_url(self, key: str, ttl: int) -> None:
        """Local files have no URL: the download route streams them after its checks."""
        return None


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


# ─────────────────────────────────────────────────────────────────────────────
# Supabase Storage backend
# ─────────────────────────────────────────────────────────────────────────────

_CONTENT_TYPES = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class SupabaseStorageBackend:
    """
    Supabase Storage backend, through its REST API (https://supabase.com/docs/reference/api).

    The bucket must be private (no public policy): objects have no public URL, and a
    download is a signed URL that stops working after its expiry. The key is the object's
    path in the bucket, a random name. Calls are made with the project's service-role key,
    which bypasses row-level security: it stays on the server, is sent only in request
    headers, and is never logged, returned or put in an error message.
    """

    provider = "supabase"
    _TIMEOUT_SECONDS = 30.0

    def __init__(self, url: str, service_role_key: str, bucket: str, *, transport=None):
        self._base = f"{url.rstrip('/')}/storage/v1"
        self._bucket = quote(bucket, safe="")
        self._headers = {"Authorization": f"Bearer {service_role_key}", "apikey": service_role_key}
        self._transport = transport          # tests pass an httpx.MockTransport

    def __repr__(self) -> str:
        return f"SupabaseStorageBackend(bucket={self._bucket!r})"

    # ── calls ─────────────────────────────────────────────────────────────────

    def upload(self, file_bytes: bytes, ext: str) -> StorageResult:
        """Upload bytes as a new object under a random key; an existing key is never overwritten."""
        key = _random_key(ext)
        content_type = _CONTENT_TYPES.get(key.rpartition(".")[2], "application/octet-stream")
        self._send(
            "POST", f"/object/{self._bucket}/{key}",
            files={"file": (key, file_bytes, content_type)},
            headers={"x-upsert": "false"},
        )
        size_kb = max(1, round(len(file_bytes) / 1024))
        logger.info("Supabase upload complete", extra={"key": key, "size_kb": size_kb})
        return StorageResult(key=key, size_kb=size_kb, provider=self.provider)

    def signed_url(self, key: str, ttl: int) -> str:
        """A download URL for key that Supabase stops honouring after ttl seconds."""
        _check_key(key)
        response = self._send(
            "POST", f"/object/sign/{self._bucket}/{quote(key, safe='/')}", json={"expiresIn": int(ttl)},
        )
        signed = response.json().get("signedURL")
        if not signed:
            raise StorageError("Supabase Storage returned no signed URL.")
        return f"{self._base}/{signed.lstrip('/')}"

    def download_bytes(self, key: str) -> bytes:
        _check_key(key)
        data = self._send("GET", f"/object/{self._bucket}/{quote(key, safe='/')}").content
        if not data:
            raise StorageError("Supabase Storage returned an empty file.")
        return data

    def delete(self, key: str) -> None:
        """Delete the object; best-effort, a failure is logged and never raised."""
        try:
            _check_key(key)
            self._send("DELETE", f"/object/{self._bucket}", json={"prefixes": [key]})
            logger.info("Supabase file deleted", extra={"key": key})
        except StorageError as exc:
            logger.warning("Failed to delete a Supabase file", extra={"key": key, "error": str(exc)})

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _send(self, method: str, path: str, **kwargs) -> "httpx.Response":
        try:
            with httpx.Client(
                base_url=self._base, headers=self._headers,
                timeout=self._TIMEOUT_SECONDS, transport=self._transport,
            ) as client:
                response = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # the exception text can contain the URL; the class name is enough
            raise StorageError(f"Supabase Storage request failed: {type(exc).__name__}") from exc
        if response.is_success:
            return response
        message = _error_message(response)
        if _is_not_found(response):
            raise StorageNotFound(f"Supabase Storage: not found ({message}).")
        raise StorageError(f"Supabase Storage returned {response.status_code}: {message}")


def _check_key(key: str) -> None:
    """Refuse keys that are empty or could climb out of the bucket's key space."""
    if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
        raise StorageError("Invalid storage key.")


def _error_json(response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _is_not_found(response) -> bool:
    # Supabase reports a missing object as HTTP 400 with {"statusCode": "404"} as well as 404.
    return response.status_code == 404 or str(_error_json(response).get("statusCode")) == "404"


def _error_message(response) -> str:
    return str(_error_json(response).get("message") or "no message")[:200]


# ─────────────────────────────────────────────────────────────────────────────
# Registry: the one place a provider name becomes a backend
# ─────────────────────────────────────────────────────────────────────────────

_BUILDERS: dict[str, Callable[[Callable], StorageBackend]] = {
    "local":      _build_local,
    "cloudinary": _build_cloudinary,
    "supabase":   _build_supabase,
}
