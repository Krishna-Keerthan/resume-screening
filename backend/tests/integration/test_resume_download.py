"""
GET /api/v1/resumes/<id>/download, plus the other places that must use
Resume.storage_key (not the legacy file_path) to reach the stored file.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.storage_service import LocalStorageBackend, StorageError, StorageService
from app.utils.file_helpers import safe_download_name

BASE = "/api/v1/resumes"
PDF_BYTES = b"%PDF-1.4 stored resume bytes"


# ─── safe_download_name ───────────────────────────────────────────────────────

@pytest.mark.parametrize("filename, ext, expected", [
    ("cv.pdf", "pdf", "cv.pdf"),
    ("My Résumé.docx", "docx", "My Résumé.docx"),
    ('a"b.pdf', "pdf", "ab.pdf"),
    ("../../etc/passwd.pdf", "pdf", "passwd.pdf"),
    ("C:\\Users\\bob\\cv.docx", "docx", "cv.docx"),
    ("cv.exe", "pdf", "cv.pdf"),
    ("my.cv.final.pdf", "pdf", "my.cv.final.pdf"),
    ("", "pdf", "resume.pdf"),
    (".pdf", "pdf", "resume.pdf"),
    ("///", "docx", "resume.docx"),
    ("   .hidden.pdf", "pdf", "hidden.pdf"),
])
def test_safe_download_name(filename, ext, expected):
    assert safe_download_name(filename, ext) == expected


def test_safe_download_name_strips_control_characters_and_quotes():
    name = safe_download_name('evil\r\nX-Injected: 1\x00\x7f"\'.pdf', "pdf")
    assert not any(ord(c) < 32 or ord(c) == 127 for c in name)
    assert '"' not in name and "\n" not in name and name.endswith(".pdf")


def test_safe_download_name_caps_the_length():
    assert len(safe_download_name("a" * 500 + ".pdf", "pdf")) <= 105


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def local_storage(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, "STORAGE_PROVIDER", "local")
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    return LocalStorageBackend(str(tmp_path / "uploads"))


@pytest.fixture()
def stored_resume(db, resume_a, local_storage):
    key = local_storage.upload(PDF_BYTES, "pdf").key
    resume_a.storage_key = key
    resume_a.file_path = "legacy-column-must-not-be-used"
    db.session.commit()
    return resume_a


# ─── local backend: streamed after the ownership check ────────────────────────

def test_owner_gets_the_bytes(check_access, stored_resume, candidate_a, candidate_b):
    r = check_access("GET", f"{BASE}/{stored_resume.id}/download", owner=candidate_a, other=candidate_b)
    assert r.get_data() == PDF_BYTES


def test_a_recruiter_with_an_application_gets_the_bytes(
    check_access, stored_resume, application_a, recruiter_a, recruiter_b
):
    r = check_access("GET", f"{BASE}/{stored_resume.id}/download", owner=recruiter_a, other=recruiter_b)
    assert r.get_data() == PDF_BYTES


def test_a_recruiter_without_an_application_is_403(client, stored_resume, recruiter_a, headers_for):
    assert client.get(f"{BASE}/{stored_resume.id}/download", headers=headers_for(recruiter_a)).status_code == 403


def test_response_headers_are_safe(client, db, stored_resume, candidate_a, headers_for):
    stored_resume.filename = 'evil"\r\n../name.exe'
    stored_resume.file_type = "pdf"
    db.session.commit()

    r = client.get(f"{BASE}/{stored_resume.id}/download", headers=headers_for(candidate_a))

    assert r.status_code == 200
    assert r.mimetype == "application/pdf"            # from the validated extension, not the filename
    disposition = r.headers["Content-Disposition"]
    assert disposition.startswith("attachment")
    assert "\r" not in disposition and "\n" not in disposition and "/" not in disposition
    assert "name.pdf" in disposition
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in r.headers["Cache-Control"] and "private" in r.headers["Cache-Control"]


def test_docx_is_served_with_the_docx_content_type(client, db, stored_resume, candidate_a, headers_for):
    stored_resume.file_type = "docx"
    db.session.commit()
    r = client.get(f"{BASE}/{stored_resume.id}/download", headers=headers_for(candidate_a))
    assert r.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_the_response_never_reveals_where_the_file_is_stored(client, stored_resume, candidate_a, headers_for, tmp_path):
    r = client.get(f"{BASE}/{stored_resume.id}/download", headers=headers_for(candidate_a))
    assert str(tmp_path) not in repr(r.headers) and stored_resume.storage_key not in repr(r.headers)


def test_a_missing_file_is_404(client, db, stored_resume, local_storage, candidate_a, headers_for):
    local_storage.delete(stored_resume.storage_key)
    r = client.get(f"{BASE}/{stored_resume.id}/download", headers=headers_for(candidate_a))
    assert r.status_code == 404
    assert r.get_json()["error"]["error_code"] == "FILE_NOT_FOUND"


def test_a_resume_without_a_storage_key_is_404_even_if_file_path_is_set(
    client, db, stored_resume, candidate_a, headers_for
):
    stored_resume.storage_key = None
    db.session.commit()
    r = client.get(f"{BASE}/{stored_resume.id}/download", headers=headers_for(candidate_a))
    assert r.status_code == 404
    assert r.get_json()["error"]["error_code"] == "FILE_NOT_FOUND"


def test_a_deleted_resume_is_404(client, db, stored_resume, candidate_a, headers_for):
    stored_resume.is_deleted = True
    db.session.commit()
    assert client.get(f"{BASE}/{stored_resume.id}/download", headers=headers_for(candidate_a)).status_code == 404


def test_an_unknown_resume_is_404(client, db, candidate_a, headers_for):
    assert client.get(f"{BASE}/no-such/download", headers=headers_for(candidate_a)).status_code == 404


# ─── Cloudinary: a signed URL that expires in 5 minutes ───────────────────────

@pytest.fixture()
def cloudinary_storage(app, monkeypatch):
    fake = MagicMock(provider="cloudinary")
    fake.signed_url.return_value = "https://signed.example/download?sig=1"
    monkeypatch.setitem(app.config, "STORAGE_PROVIDER", "cloudinary")
    with patch.object(StorageService, "from_config", return_value=fake):
        yield fake


def test_cloudinary_resume_returns_a_signed_url_that_expires_in_300_seconds(
    check_access, db, resume_a, cloudinary_storage, candidate_a, candidate_b
):
    resume_a.storage_key = "resumes/abc.pdf"
    db.session.commit()

    r = check_access("GET", f"{BASE}/{resume_a.id}/download", owner=candidate_a, other=candidate_b)

    assert r.get_json()["data"] == {"url": "https://signed.example/download?sig=1", "expires_in": 300}
    cloudinary_storage.signed_url.assert_called_once_with("resumes/abc.pdf", ttl=300)


def test_the_ttl_comes_from_config(app, client, db, resume_a, cloudinary_storage, candidate_a, headers_for, monkeypatch):
    monkeypatch.setitem(app.config, "DOWNLOAD_URL_TTL_SECONDS", 60)
    resume_a.storage_key = "resumes/abc.pdf"
    db.session.commit()
    r = client.get(f"{BASE}/{resume_a.id}/download", headers=headers_for(candidate_a))
    assert r.get_json()["data"]["expires_in"] == 60
    cloudinary_storage.signed_url.assert_called_once_with("resumes/abc.pdf", ttl=60)


def test_a_signing_failure_is_a_502_without_internals(
    client, db, resume_a, cloudinary_storage, candidate_a, headers_for
):
    resume_a.storage_key = "resumes/abc.pdf"
    db.session.commit()
    cloudinary_storage.signed_url.side_effect = StorageError("api_secret=hunter2 rejected")
    r = client.get(f"{BASE}/{resume_a.id}/download", headers=headers_for(candidate_a))
    assert r.status_code == 502
    assert "hunter2" not in r.get_data(as_text=True)


# ─── delete and analyze use storage_key ───────────────────────────────────────

@pytest.fixture()
def fake_storage():
    fake = MagicMock(provider="local")
    with patch.object(StorageService, "from_config", return_value=fake):
        yield fake


def test_delete_removes_the_file_by_storage_key(client, db, resume_a, candidate_a, headers_for, fake_storage):
    resume_a.storage_key = "the-key.pdf"
    resume_a.file_path = "legacy-path.pdf"
    db.session.commit()

    assert client.delete(f"{BASE}/{resume_a.id}", headers=headers_for(candidate_a)).status_code == 204

    fake_storage.delete.assert_called_once_with("the-key.pdf")


def test_delete_never_falls_back_to_file_path(client, db, resume_a, candidate_a, headers_for, fake_storage):
    resume_a.storage_key = None
    resume_a.file_path = "legacy-path.pdf"
    db.session.commit()

    assert client.delete(f"{BASE}/{resume_a.id}", headers=headers_for(candidate_a)).status_code == 204

    fake_storage.delete.assert_not_called()


def test_analyze_force_refresh_downloads_by_storage_key(
    client, db, resume_a, candidate_a, headers_for, fake_storage, mock_services
):
    resume_a.storage_key = "the-key.pdf"
    resume_a.file_path = "legacy-path.pdf"
    db.session.commit()
    fake_storage.download_bytes.return_value = PDF_BYTES
    mock_services.resume_parser.parse_bytes.return_value = SimpleNamespace(success=False, parse_error="stubbed")

    client.post(f"{BASE}/{resume_a.id}/analyze", json={"force_refresh": True}, headers=headers_for(candidate_a))

    fake_storage.download_bytes.assert_called_once_with("the-key.pdf")


def test_analyze_force_refresh_without_a_storage_key_is_422(
    client, db, resume_a, candidate_a, headers_for, fake_storage, mock_services
):
    resume_a.storage_key = None
    db.session.commit()

    r = client.post(f"{BASE}/{resume_a.id}/analyze", json={"force_refresh": True}, headers=headers_for(candidate_a))

    assert r.status_code == 422
    assert r.get_json()["error"]["error_code"] == "NO_STORAGE_KEY"
    fake_storage.download_bytes.assert_not_called()


# ─── any backend that has a signed URL is served the same way ─────────────────

class _FakeUrlBackend:
    """A provider the download route has never heard of."""
    provider = "made-up"

    def __init__(self):
        self.signed = []

    def signed_url(self, key, ttl):
        self.signed.append((key, ttl))
        return "https://signed.example/object?token=t"

    def download_bytes(self, key):
        raise AssertionError("a backend with a signed URL is not streamed through the app")


def _register(app, monkeypatch, backend):
    from app.services import storage_service

    monkeypatch.setitem(app.config, "STORAGE_PROVIDER", "made-up")
    monkeypatch.setitem(storage_service._BUILDERS, "made-up", lambda cfg: backend)


def test_the_route_serves_a_signed_url_for_any_provider_without_naming_it(
    app, check_access, db, resume_a, candidate_a, candidate_b, monkeypatch
):
    backend = _FakeUrlBackend()
    _register(app, monkeypatch, backend)
    resume_a.storage_key = "abc.pdf"
    db.session.commit()

    r = check_access("GET", f"{BASE}/{resume_a.id}/download", owner=candidate_a, other=candidate_b)

    assert r.get_json()["data"] == {"url": "https://signed.example/object?token=t", "expires_in": 300}
    assert backend.signed == [("abc.pdf", 300)]


def test_a_file_the_store_does_not_have_is_404_for_any_provider(
    app, client, db, resume_a, candidate_a, headers_for, monkeypatch
):
    from app.services.storage_service import StorageNotFound

    class _Missing:
        provider = "made-up"
        signed_url = staticmethod(lambda key, ttl: None)

        @staticmethod
        def download_bytes(key):
            raise StorageNotFound("gone")

    _register(app, monkeypatch, _Missing())
    resume_a.storage_key = "abc.pdf"
    db.session.commit()

    r = client.get(f"{BASE}/{resume_a.id}/download", headers=headers_for(candidate_a))

    assert (r.status_code, r.get_json()["error"]["error_code"]) == (404, "FILE_NOT_FOUND")


def test_any_other_store_failure_is_502_for_any_provider(
    app, client, db, resume_a, candidate_a, headers_for, monkeypatch
):
    class _Broken:
        provider = "made-up"
        signed_url = staticmethod(lambda key, ttl: None)

        @staticmethod
        def download_bytes(key):
            raise StorageError("connection reset")

    _register(app, monkeypatch, _Broken())
    resume_a.storage_key = "abc.pdf"
    db.session.commit()

    r = client.get(f"{BASE}/{resume_a.id}/download", headers=headers_for(candidate_a))

    assert (r.status_code, r.get_json()["error"]["error_code"]) == (502, "STORAGE_UNAVAILABLE")
