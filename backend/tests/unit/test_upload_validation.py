"""
validate_content: the file's bytes must match its extension (checked by
signature, not by the client's Content-Type), and a DOCX must be a sane zip.
"""
import io
import zipfile

import pytest

from app.core.exceptions import ResumeUploadFailed
from app.utils.file_helpers import (
    DOCX_MAX_ENTRIES,
    DOCX_MAX_UNCOMPRESSED_BYTES,
    validate_content,
)


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


MINIMAL_DOCX_PARTS = {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"}


def docx(**extra) -> bytes:
    return make_zip({**MINIMAL_DOCX_PARTS, **extra})


# ─── PDF ──────────────────────────────────────────────────────────────────────

def test_a_pdf_with_the_pdf_signature_is_accepted():
    validate_content(b"%PDF-1.7\n...", "pdf")


@pytest.mark.parametrize("data", [b"plain text", b" %PDF-1.4", b"", docx(), b"<html>%PDF-</html>"])
def test_a_pdf_without_the_signature_at_offset_zero_is_rejected(data):
    with pytest.raises(ResumeUploadFailed):
        validate_content(data, "pdf")


# ─── DOCX ─────────────────────────────────────────────────────────────────────

def test_a_minimal_docx_is_accepted():
    validate_content(docx(), "docx")


def test_a_pdf_renamed_to_docx_is_rejected():
    with pytest.raises(ResumeUploadFailed):
        validate_content(b"%PDF-1.4 ...", "docx")


def test_a_docx_renamed_to_pdf_is_rejected():
    with pytest.raises(ResumeUploadFailed):
        validate_content(docx(), "pdf")


def test_a_plain_zip_without_word_document_xml_is_rejected():
    with pytest.raises(ResumeUploadFailed, match="word/document.xml"):
        validate_content(make_zip({"[Content_Types].xml": b"<Types/>", "readme.txt": b"hi"}), "docx")


def test_a_zip_without_content_types_is_rejected():
    with pytest.raises(ResumeUploadFailed):
        validate_content(make_zip({"word/document.xml": b"<w:document/>"}), "docx")


def test_a_corrupt_zip_is_rejected():
    with pytest.raises(ResumeUploadFailed):
        validate_content(docx()[:-30], "docx")


# ─── DOCX limits ──────────────────────────────────────────────────────────────

def test_the_documented_limits():
    assert DOCX_MAX_ENTRIES == 100
    assert DOCX_MAX_UNCOMPRESSED_BYTES == 50 * 1024 * 1024


def _docx_with_entries(total: int) -> bytes:
    return make_zip({**MINIMAL_DOCX_PARTS, **{f"word/media/i{n}.png": b"x" for n in range(total - 2)}})


def test_exactly_100_entries_is_accepted():
    validate_content(_docx_with_entries(100), "docx")


def test_101_entries_is_rejected():
    with pytest.raises(ResumeUploadFailed, match="entries"):
        validate_content(_docx_with_entries(101), "docx")


def test_more_than_50_mb_uncompressed_is_rejected():
    bomb = docx(**{"word/media/zeros.bin": b"\0" * (DOCX_MAX_UNCOMPRESSED_BYTES + 1)})
    assert len(bomb) < 200_000                      # it compresses to almost nothing
    with pytest.raises(ResumeUploadFailed, match="uncompressed"):
        validate_content(bomb, "docx")


def test_exactly_50_mb_uncompressed_is_accepted():
    parts_size = sum(len(v) for v in MINIMAL_DOCX_PARTS.values())
    ok = docx(**{"word/media/zeros.bin": b"\0" * (DOCX_MAX_UNCOMPRESSED_BYTES - parts_size)})
    validate_content(ok, "docx")


@pytest.mark.parametrize("name", ["word/embeddings/inner.docx", "word/embeddings/a.zip", "x/b.jar", "c.7z", "d.tar.gz", "e.rar"])
def test_an_entry_with_an_archive_name_is_rejected(name):
    with pytest.raises(ResumeUploadFailed, match="archive"):
        validate_content(docx(**{name: b"anything"}), "docx")


@pytest.mark.parametrize("magic", [
    b"PK\x03\x04rest", b"\x1f\x8b\x08rest", b"7z\xbc\xaf\x27\x1crest", b"Rar!\x1a\x07\x00rest",
])
def test_an_entry_that_starts_with_an_archive_signature_is_rejected_whatever_its_name(magic):
    with pytest.raises(ResumeUploadFailed, match="archive"):
        validate_content(docx(**{"word/media/image1.png": magic}), "docx")


def test_a_nested_docx_inside_the_docx_is_rejected():
    with pytest.raises(ResumeUploadFailed, match="archive"):
        validate_content(docx(**{"word/media/image1.png": docx()}), "docx")


def test_ordinary_embedded_media_is_fine():
    validate_content(docx(**{"word/media/image1.png": b"\x89PNG\r\n\x1a\n...."}), "docx")
