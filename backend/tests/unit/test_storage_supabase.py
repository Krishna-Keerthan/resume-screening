"""
The Supabase Storage backend: the exact HTTP calls it makes, how it handles errors, and
that the service-role key stays server-side. The fake server is tests/unit/fake_supabase.py.

The behaviour every backend shares is tested in test_storage_contract.py.
"""
import logging
import re

import httpx
import pytest

from app.services.storage_service import (
    StorageError,
    StorageNotFound,
    StorageService,
    SupabaseStorageBackend,
)
from tests.unit.fake_supabase import BUCKET, JWT_SERVICE_KEY, SERVICE_KEY, URL, FakeSupabase

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
    assert call.headers["apikey"] == SERVICE_KEY


def test_a_trailing_slash_on_the_url_makes_no_difference(fake):
    backend = SupabaseStorageBackend(URL + "/", SERVICE_KEY, BUCKET, transport=fake.transport)

    backend.upload(PDF, "pdf")

    assert fake.calls[0].path.startswith(f"/storage/v1/object/{BUCKET}/")


# ─── which header carries the key ─────────────────────────────────────────────

def test_a_new_style_secret_key_goes_in_the_apikey_header_only(backend, fake):
    # Supabase: "Send publishable and secret keys on the apikey header, not on Authorization: Bearer"
    backend.upload(PDF, "pdf")

    headers = fake.calls[0].headers
    assert headers["apikey"] == SERVICE_KEY and "authorization" not in headers


def test_a_legacy_service_role_jwt_goes_in_both_headers():
    fake = FakeSupabase(service_key=JWT_SERVICE_KEY)
    backend = SupabaseStorageBackend(URL, JWT_SERVICE_KEY, BUCKET, transport=fake.transport)

    backend.upload(PDF, "pdf")

    headers = fake.calls[0].headers
    assert headers["apikey"] == JWT_SERVICE_KEY
    assert headers["authorization"] == f"Bearer {JWT_SERVICE_KEY}"


def test_bucket_is_private_reads_the_bucket_flag(backend, fake):
    assert backend.bucket_is_private() is True
    assert fake.calls[-1].method == "GET" and fake.calls[-1].path == f"/storage/v1/bucket/{BUCKET}"

    fake.public = True
    assert backend.bucket_is_private() is False


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


def test_a_legacy_jwt_key_is_not_logged_or_shown_either(caplog):
    fake = FakeSupabase(service_key=JWT_SERVICE_KEY)
    backend = SupabaseStorageBackend(URL, JWT_SERVICE_KEY, BUCKET, transport=fake.transport)

    with caplog.at_level(logging.DEBUG):
        key = backend.upload(PDF, "pdf").key
        url = backend.signed_url(key, ttl=300)
        fake.fail_with = 500
        with pytest.raises(StorageError) as raised:
            backend.download_bytes(key)

    assert JWT_SERVICE_KEY not in " ".join([caplog.text, repr(backend), url, str(raised.value)])


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


# ─── one HTTP client, not one per call ────────────────────────────────────────

@pytest.fixture()
def clients_built(monkeypatch):
    """Count the httpx clients the backend builds."""
    import httpx

    built = []
    real = httpx.Client

    def counting(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("app.services.storage_service.httpx.Client", counting)
    return built


def test_every_call_reuses_one_http_client(backend, clients_built):
    # a client per call built a new SSL context each time: about 3 MB more RSS after 8 calls
    key = backend.upload(PDF, "pdf").key
    backend.signed_url(key, ttl=300)
    backend.download_bytes(key)
    backend.bucket_is_private()
    backend.delete(key)

    assert len(clients_built) == 1


def test_a_forked_worker_builds_its_own_client_instead_of_sharing_the_parents_sockets(
    backend, clients_built, monkeypatch
):
    import os

    backend.upload(PDF, "pdf")
    pid = os.getpid()
    monkeypatch.setattr("app.services.storage_service.os.getpid", lambda: pid + 1)

    backend.upload(PDF, "pdf")

    assert len(clients_built) == 2


def test_the_factory_returns_the_same_backend_for_the_same_settings():
    first = StorageService.from_config(_SETTINGS)

    assert StorageService.from_config(dict(_SETTINGS)) is first
    assert StorageService.from_config({**_SETTINGS, "SUPABASE_BUCKET": "other"}) is not first


# ─── reachability ─────────────────────────────────────────────────────────────

def test_is_reachable_asks_for_the_bucket_and_nothing_else(backend, fake):
    assert backend.is_reachable() is True

    (call,) = fake.calls
    assert (call.method, call.path) == ("GET", f"/storage/v1/bucket/{BUCKET}")


def test_is_reachable_is_false_for_a_wrong_key(fake):
    wrong = SupabaseStorageBackend(URL, "sb_secret_wrong", BUCKET, transport=fake.transport)

    assert wrong.is_reachable() is False


def test_is_reachable_is_false_for_a_missing_bucket(fake):
    missing = SupabaseStorageBackend(URL, SERVICE_KEY, "no-such-bucket", transport=fake.transport)

    assert missing.is_reachable() is False


def test_is_reachable_is_false_when_supabase_errors(backend, fake):
    fake.fail_with = 503

    assert backend.is_reachable() is False


def test_is_reachable_is_false_when_the_network_fails():
    def refuse(request):
        raise httpx.ConnectError("secret-host.internal refused")

    backend = SupabaseStorageBackend(URL, SERVICE_KEY, BUCKET, transport=httpx.MockTransport(refuse))

    assert backend.is_reachable() is False
