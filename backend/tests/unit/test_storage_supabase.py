"""
The Supabase Storage backend: the exact HTTP calls it makes, how it handles errors, and
that the service-role key stays server-side. The fake server is tests/unit/fake_supabase.py.

The behaviour every backend shares is tested in test_storage_contract.py.
"""
import logging
import re

import pytest

from app.services.storage_service import (
    StorageError,
    StorageNotFound,
    StorageService,
    SupabaseStorageBackend,
)
from tests.unit.fake_supabase import BUCKET, SERVICE_KEY, URL, FakeSupabase

PDF = b"%PDF-1.4 supabase test"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture()
def fake():
    return FakeSupabase()


@pytest.fixture()
def backend(fake):
    return SupabaseStorageBackend(URL, SERVICE_KEY, BUCKET, transport=fake.transport)


# ─── the exact calls ──────────────────────────────────────────────────────────

def test_upload_posts_a_multipart_file_under_a_random_key_without_overwriting(backend, fake):
    key = backend.upload(PDF, "pdf").key

    (call,) = fake.calls
    assert (call.method, call.path) == ("POST", f"/storage/v1/object/{BUCKET}/{key}")
    assert call.headers["authorization"] == f"Bearer {SERVICE_KEY}"
    assert call.headers["apikey"] == SERVICE_KEY
    assert call.headers["x-upsert"] == "false"
    assert call.body == {"filename": key, "content_type": "application/pdf", "bytes": PDF}
    assert fake.objects == {key: PDF}


@pytest.mark.parametrize("ext, content_type", [
    ("pdf", "application/pdf"), ("docx", DOCX_TYPE), ("weird", "application/octet-stream"),
])
def test_the_content_type_follows_the_validated_extension(backend, fake, ext, content_type):
    backend.upload(PDF, ext)

    assert fake.calls[0].body["content_type"] == content_type


def test_signed_url_posts_the_expiry_in_seconds_and_builds_an_absolute_url(backend, fake):
    key = backend.upload(PDF, "pdf").key
    fake.calls.clear()

    url = backend.signed_url(key, ttl=300)

    (call,) = fake.calls
    assert (call.method, call.path) == ("POST", f"/storage/v1/object/sign/{BUCKET}/{key}")
    assert call.body == {"expiresIn": 300}
    assert url == f"{URL}/storage/v1/object/sign/{BUCKET}/{key}?token=tok-1"
    assert fake.signed == [(key, 300)]


def test_signed_url_of_a_missing_object_is_storage_not_found(backend):
    with pytest.raises(StorageNotFound):
        backend.signed_url("0" * 32 + ".pdf", ttl=300)


def test_delete_sends_the_key_as_a_prefix(backend, fake):
    key = backend.upload(PDF, "pdf").key
    fake.calls.clear()

    backend.delete(key)

    (call,) = fake.calls
    assert (call.method, call.path, call.body) == ("DELETE", f"/storage/v1/object/{BUCKET}", {"prefixes": [key]})
    assert fake.objects == {}


def test_download_is_an_authenticated_get_of_the_object(backend, fake):
    key = backend.upload(PDF, "pdf").key
    fake.calls.clear()

    assert backend.download_bytes(key) == PDF

    (call,) = fake.calls
    assert (call.method, call.path) == ("GET", f"/storage/v1/object/{BUCKET}/{key}")
    assert call.headers["authorization"] == f"Bearer {SERVICE_KEY}"


def test_a_trailing_slash_on_the_url_makes_no_difference(fake):
    backend = SupabaseStorageBackend(URL + "/", SERVICE_KEY, BUCKET, transport=fake.transport)

    backend.upload(PDF, "pdf")

    assert fake.calls[0].path.startswith(f"/storage/v1/object/{BUCKET}/")


# ─── errors ───────────────────────────────────────────────────────────────────

def test_a_missing_object_is_reported_as_400_by_supabase_and_is_still_not_found(backend):
    # the real API answers HTTP 400 with {"statusCode": "404"} for a missing object
    with pytest.raises(StorageNotFound):
        backend.download_bytes("0" * 32 + ".pdf")


def test_a_server_error_is_a_storage_error_not_a_not_found(backend, fake):
    fake.fail_with = 500

    with pytest.raises(StorageError) as raised:
        backend.download_bytes("0" * 32 + ".pdf")

    assert not isinstance(raised.value, StorageNotFound)
    assert "500" in str(raised.value)


def test_upload_failure_is_a_storage_error(backend, fake):
    fake.fail_with = 503

    with pytest.raises(StorageError):
        backend.upload(PDF, "pdf")


def test_a_wrong_service_key_is_a_storage_error_that_does_not_echo_it(fake):
    backend = SupabaseStorageBackend(URL, "wrong-key-value", BUCKET, transport=fake.transport)

    with pytest.raises(StorageError) as raised:
        backend.upload(PDF, "pdf")

    assert "401" in str(raised.value)
    assert "wrong-key-value" not in str(raised.value) and SERVICE_KEY not in str(raised.value)


def test_an_unreachable_store_is_a_storage_error():
    import httpx

    def refuse(request):
        raise httpx.ConnectError("no route to host", request=request)

    backend = SupabaseStorageBackend(URL, SERVICE_KEY, BUCKET, transport=httpx.MockTransport(refuse))

    with pytest.raises(StorageError) as raised:
        backend.upload(PDF, "pdf")
    assert "ConnectError" in str(raised.value)
    backend.delete("0" * 32 + ".pdf")             # best-effort: swallowed


@pytest.mark.parametrize("key", ["", "/abs.pdf", "../x.pdf", "a/../b.pdf", "a\\b.pdf"])
def test_keys_that_could_leave_the_bucket_prefix_are_refused_before_any_call(backend, fake, key):
    with pytest.raises(StorageError):
        backend.download_bytes(key)
    with pytest.raises(StorageError):
        backend.signed_url(key, ttl=300)
    backend.delete(key)

    assert fake.calls == []


# ─── the service-role key stays on the server ─────────────────────────────────

def test_the_key_is_never_logged_returned_or_shown(backend, fake, caplog):
    with caplog.at_level(logging.DEBUG):
        key = backend.upload(PDF, "pdf").key
        url = backend.signed_url(key, ttl=300)
        backend.download_bytes(key)
        backend.delete(key)
        fake.fail_with = 500
        with pytest.raises(StorageError) as raised:
            backend.upload(PDF, "pdf")

    everything = " ".join([caplog.text, repr(backend), str(backend), url, str(raised.value)])
    assert SERVICE_KEY not in everything


def test_the_signed_url_is_not_logged(backend, caplog):
    with caplog.at_level(logging.DEBUG):
        key = backend.upload(PDF, "pdf").key
        url = backend.signed_url(key, ttl=300)

    assert "token=" not in caplog.text and url not in caplog.text


# ─── the factory ──────────────────────────────────────────────────────────────

_SETTINGS = {
    "STORAGE_PROVIDER": "supabase",
    "SUPABASE_URL": URL,
    "SUPABASE_SERVICE_ROLE_KEY": SERVICE_KEY,
    "SUPABASE_BUCKET": BUCKET,
}


def test_the_factory_builds_the_supabase_backend_from_the_three_settings():
    backend = StorageService.from_config(_SETTINGS)

    assert isinstance(backend, SupabaseStorageBackend) and backend.provider == "supabase"


@pytest.mark.parametrize("missing", ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_BUCKET"])
def test_a_missing_setting_stops_startup_and_names_it_without_revealing_the_others(missing):
    with pytest.raises(StorageError) as stopped:
        StorageService.from_config({**_SETTINGS, missing: ""})

    message = str(stopped.value)
    assert missing in message
    assert SERVICE_KEY not in message and URL not in message


def test_all_three_missing_are_listed_together():
    with pytest.raises(StorageError) as stopped:
        StorageService.from_config({"STORAGE_PROVIDER": "supabase"})

    assert all(name in str(stopped.value) for name in
               ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_BUCKET"))


@pytest.mark.parametrize("url", ["project.supabase.co", "ftp://project.supabase.co", "supabase"])
def test_the_url_must_be_http_or_https(url):
    with pytest.raises(StorageError, match="SUPABASE_URL"):
        StorageService.from_config({**_SETTINGS, "SUPABASE_URL": url})


def test_a_url_with_a_path_after_the_host_is_refused():
    # the backend adds /storage/v1 itself; a pasted dashboard URL would double it
    with pytest.raises(StorageError, match="SUPABASE_URL"):
        StorageService.from_config({**_SETTINGS, "SUPABASE_URL": URL + "/storage/v1"})


def test_the_object_key_pattern_is_the_shared_one(backend):
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", backend.upload(PDF, "pdf").key)
