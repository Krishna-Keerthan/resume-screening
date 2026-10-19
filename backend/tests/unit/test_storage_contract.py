"""
Contract tests: the behaviour every storage backend must have, run against each one.

A backend is anything StorageService.from_config can return. To add one, add a builder to
BACKENDS; every test below then runs against it. Backends that talk to a service are built
on a fake transport, so the same tests also check the exact calls they make (see
test_storage_supabase.py for those).

The contract:
  upload(bytes, ext)  -> StorageResult(key, size_kb, provider); the key is random, never
                         derived from a user's filename, and carries only a plain extension
  download_bytes(key) -> the bytes, or StorageNotFound if there is no such object
  delete(key)         -> removes the object; never raises
  signed_url(key, ttl)-> a URL that stops working after ttl seconds, or None for a backend
                         with no direct URL (the route then serves the bytes itself)
  is_reachable()      -> True if the store can be used right now, else False; never raises
  provider            -> its name, used only for logging and in the upload response
"""
import re

import pytest

from app.services.storage_service import (
    LocalStorageBackend,
    StorageError,
    StorageNotFound,
    StorageResult,
    SupabaseStorageBackend,
)
from tests.unit.fake_supabase import BUCKET, SERVICE_KEY, URL, FakeSupabase

PDF = b"%PDF-1.4 contract test"


def _local(tmp_path):
    return LocalStorageBackend(str(tmp_path / "uploads"))


def _supabase(tmp_path):
    return SupabaseStorageBackend(URL, SERVICE_KEY, BUCKET, transport=FakeSupabase().transport)


BACKENDS = {"local": _local, "supabase": _supabase}


@pytest.fixture(params=sorted(BACKENDS))
def backend(request, tmp_path):
    return BACKENDS[request.param](tmp_path)


def test_a_backend_names_itself(backend):
    assert isinstance(backend.provider, str) and backend.provider


@pytest.mark.parametrize("ext", ["pdf", "docx"])
def test_upload_returns_a_random_key_with_only_the_plain_extension(backend, ext):
    result = backend.upload(PDF, ext)

    assert isinstance(result, StorageResult)
    assert result.provider == backend.provider
    assert re.fullmatch(rf"[0-9a-f]{{32}}\.{ext}", result.key)
    assert result.size_kb >= 1


@pytest.mark.parametrize("hostile", ["../../etc/passwd", "pdf/../x", "résumé.pdf", "PDF;rm -rf", ""])
def test_a_hostile_extension_never_reaches_the_key(backend, hostile):
    key = backend.upload(PDF, hostile).key

    assert re.fullmatch(r"[0-9a-f]{32}(\.[a-z0-9]{1,10})?", key)


def test_keys_are_unique(backend):
    assert len({backend.upload(PDF, "pdf").key for _ in range(20)}) == 20


def test_what_was_uploaded_can_be_downloaded(backend):
    key = backend.upload(PDF, "pdf").key

    assert backend.download_bytes(key) == PDF


def test_downloading_an_unknown_key_raises_storage_not_found(backend):
    with pytest.raises(StorageNotFound):
        backend.download_bytes("0" * 32 + ".pdf")


def test_storage_not_found_is_a_storage_error():
    assert issubclass(StorageNotFound, StorageError)


def test_delete_removes_the_object(backend):
    key = backend.upload(PDF, "pdf").key

    backend.delete(key)

    with pytest.raises(StorageNotFound):
        backend.download_bytes(key)


@pytest.mark.parametrize("key", ["0" * 32 + ".pdf", "", "../outside.pdf"])
def test_delete_never_raises(backend, key):
    backend.delete(key)


def test_a_signed_url_is_a_string_or_none(backend):
    url = backend.signed_url(backend.upload(PDF, "pdf").key, ttl=300)

    assert url is None or (isinstance(url, str) and url.startswith("https://"))


def test_a_working_backend_is_reachable(backend):
    assert backend.is_reachable() is True
