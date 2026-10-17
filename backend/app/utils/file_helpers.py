"""
app/utils/file_helpers.py

File upload validation utilities.

  - validate_upload() is the entry point called from the upload route. It
    returns the lowercase extension string so the caller knows the file type.
  - save_upload() is kept for local tooling; upload_resume() uses
    StorageService instead.
  - ResumeUploadFailed is the single exception type callers catch.
"""

import io
import logging
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Tuple

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.core.exceptions import ResumeUploadFailed

logger = logging.getLogger(__name__)

# Allowed MIME types per extension
_ALLOWED_MIME: dict[str, str] = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def content_type_for(ext: str) -> str:
    """The MIME type for a validated extension."""
    return _ALLOWED_MIME.get(ext, "application/octet-stream")


def safe_download_name(filename: str | None, ext: str) -> str:
    """
    A filename that is safe to put in a Content-Disposition header.

    Keeps only the last path segment, drops control characters and quotes,
    and always ends in the validated extension.
    """
    name = re.split(r"[/\\]", filename or "")[-1]
    name = "".join(c for c in name if c.isprintable() and c not in "\"'").strip(" .")
    stem = "" if name.lower() == ext.lower() else os.path.splitext(name)[0].strip(" .")
    return f"{stem[:100] or 'resume'}.{ext}"


DOCX_MAX_ENTRIES = 100
DOCX_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_DOCX_READ_CHUNK = 64 * 1024

# First bytes of archive formats that must not be nested inside a DOCX.
_ARCHIVE_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07")
_ARCHIVE_SUFFIXES = (".zip", ".docx", ".xlsx", ".pptx", ".jar", ".7z", ".rar", ".gz", ".tgz", ".tar", ".bz2", ".xz")


def validate_content(data: bytes, ext: str) -> None:
    """
    Check that the bytes really are a PDF or DOCX, whatever the client claimed.

    PDF:  must start with "%PDF-".
    DOCX: must be a zip with [Content_Types].xml and word/document.xml, at most
          DOCX_MAX_ENTRIES entries and DOCX_MAX_UNCOMPRESSED_BYTES actually
          decompressed in total (counted while streaming, not from headers),
          and no nested archive (by entry name or leading bytes).

    Raises:
        ResumeUploadFailed: On any mismatch or limit violation.
    """
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise ResumeUploadFailed("File content is not a PDF.")
        return
    if ext != "docx":
        raise ResumeUploadFailed(f"File type '.{ext}' is not allowed.")

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ResumeUploadFailed("File content is not a DOCX document.") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > DOCX_MAX_ENTRIES:
            raise ResumeUploadFailed(
                f"DOCX has too many entries (limit {DOCX_MAX_ENTRIES})."
            )
        names = {i.filename for i in infos}
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise ResumeUploadFailed("File content is not a DOCX document (no word/document.xml).")
        total = 0
        for info in infos:
            if info.is_dir():
                continue
            if info.filename.lower().endswith(_ARCHIVE_SUFFIXES):
                raise ResumeUploadFailed("Embedded files are not supported in DOCX uploads.")
            try:
                with zf.open(info) as member:
                    first = True
                    while chunk := member.read(_DOCX_READ_CHUNK):
                        if first and chunk.startswith(_ARCHIVE_SIGNATURES):
                            raise ResumeUploadFailed("Embedded files are not supported in DOCX uploads.")
                        first = False
                        total += len(chunk)
                        if total > DOCX_MAX_UNCOMPRESSED_BYTES:
                            raise ResumeUploadFailed(
                                f"DOCX is too large when uncompressed (limit {DOCX_MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB)."
                            )
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
                raise ResumeUploadFailed("DOCX contains an unreadable entry.") from exc


def validate_upload(
    file: FileStorage,
    allowed_extensions: set[str],
    max_size_mb: int | None = None,
) -> str:
    """
    Validate an uploaded FileStorage object.

    Checks (in order):
      1. Filename is not empty.
      2. Extension is in the allowed set.
      3. MIME type matches the expected type for the extension.
      4. File is non-empty.
      5. File does not exceed max_size_mb if given.

    After this call the stream is rewound to position 0 — the caller
    can safely call file.read() or file.save() immediately after.

    Args:
        file:               Werkzeug FileStorage from request.files.
        allowed_extensions: Set of lowercase extensions e.g. {"pdf", "docx"}.
        max_size_mb:        Optional hard cap in MB.

    Returns:
        Lowercase extension string without leading dot — e.g. "pdf".

    Raises:
        ResumeUploadFailed: On any validation failure.
    """
    if not file or not file.filename:
        raise ResumeUploadFailed("No file was provided.")

    original_name = file.filename
    ext = Path(original_name).suffix.lstrip(".").lower()

    # ── Extension check ───────────────────────────────────────────────────────
    if not ext or ext not in allowed_extensions:
        raise ResumeUploadFailed(
            f"File type '.{ext}' is not allowed. "
            f"Accepted types: {', '.join(sorted(allowed_extensions))}."
        )

    # ── MIME type cross-check ─────────────────────────────────────────────────
    # Strip charset suffix: "application/pdf; charset=utf-8" → "application/pdf"
    content_type  = (file.content_type or "").split(";")[0].strip().lower()
    expected_mime = _ALLOWED_MIME.get(ext)

    if expected_mime and content_type and content_type != expected_mime:
        logger.warning(
            "MIME type mismatch for upload",
            extra={
                "filename":      original_name,
                "ext":           ext,
                "content_type":  content_type,
                "expected_mime": expected_mime,
            },
        )
        raise ResumeUploadFailed(
            f"File content does not match the declared extension '.{ext}'. "
            f"Expected MIME type '{expected_mime}', got '{content_type}'."
        )

    # ── File size check ───────────────────────────────────────────────────────
    # Seek to end to measure without reading the whole file into memory.
    file.stream.seek(0, 2)
    size_bytes = file.stream.tell()
    file.stream.seek(0)             # rewind — caller will read from start

    if size_bytes == 0:
        raise ResumeUploadFailed("Uploaded file is empty (0 bytes).")

    if max_size_mb and size_bytes > max_size_mb * 1024 * 1024:
        actual_mb = size_bytes / (1024 * 1024)
        raise ResumeUploadFailed(
            f"File exceeds the maximum upload size of {max_size_mb} MB "
            f"(got {actual_mb:.1f} MB)."
        )

    return ext


def save_upload(
    file: FileStorage,
    upload_dir: str,
    prefix: str = "",
) -> Tuple[str, int]:
    """
    Save a validated FileStorage to disk under a UUID filename.

    NOTE: This function is retained for local tooling / tests.
    The upload_resume route uses StorageService.upload() instead.

    Args:
        file:       A validated FileStorage object.
        upload_dir: Directory to save into. Created if absent.
        prefix:     Optional prefix prepended to the unique filename.

    Returns:
        (file_path, size_kb)

    Raises:
        ResumeUploadFailed: On directory creation or write failure.
    """
    try:
        Path(upload_dir).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ResumeUploadFailed(f"Failed to create upload directory: {exc}") from exc

    original_name = file.filename or "upload"
    ext           = Path(original_name).suffix.lower()
    safe_name     = secure_filename(original_name)
    unique_name   = f"{prefix}{uuid.uuid4().hex}{ext}"
    file_path     = os.path.join(upload_dir, unique_name)

    try:
        file.save(file_path)
    except Exception as exc:
        raise ResumeUploadFailed(f"Failed to save uploaded file: {exc}") from exc

    size_bytes = os.path.getsize(file_path)
    size_kb    = max(1, round(size_bytes / 1024))

    logger.info(
        "File saved to disk",
        extra={"original": safe_name, "path": file_path, "size_kb": size_kb},
    )
    return file_path, size_kb


def delete_file(file_path: str) -> None:
    """
    Delete a file from local disk. Silently ignores missing files.

    For deletion from the file store use StorageService.delete(key) instead.
    """
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info("Local file deleted", extra={"path": file_path})
    except OSError as exc:
        logger.warning("Failed to delete file %s: %s", file_path, exc)


def human_readable_size(size_bytes: int) -> str:
    """
    Format a byte count as a human-readable string.

    1500 bytes → "1.5 KB", not "1 KB".

    Returns: e.g. "2.3 MB", "512.0 KB", "800.0 B"
    """
    size: float = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"