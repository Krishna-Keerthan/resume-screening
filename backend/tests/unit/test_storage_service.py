"""
tests/unit/test_storage_service.py  —  backend selection in StorageService.
"""
from unittest.mock import patch

import pytest


def test_supabase_backend_selected_when_configured():
    from app.services.storage_service import StorageService, SupabaseStorageBackend

    backend = StorageService.from_config(_SUPABASE)
    assert isinstance(backend, SupabaseStorageBackend)
    assert backend.provider == "supabase"


_SUPABASE = {
    "STORAGE_PROVIDER":          "supabase",
    "SUPABASE_URL":              "https://project.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "key-123",
    "SUPABASE_BUCKET":           "resumes",
}


def test_local_backend_is_default(tmp_path):
    from app.services.storage_service import LocalStorageBackend, StorageService

    backend = StorageService.from_config({"UPLOAD_FOLDER": str(tmp_path)})
    assert isinstance(backend, LocalStorageBackend)




def _create_app_with(settings):
    from config.settings import TestingConfig

    patches = [patch.object(TestingConfig, k, v, create=True) for k, v in settings.items()]
    patches.append(patch("app.services.service_factory.ServiceFactory.create_all"))
    for p in patches:
        p.start()
    try:
        from app import create_app
        return create_app("testing")
    finally:
        for p in reversed(patches):
            p.stop()


def test_startup_fails_when_a_supabase_setting_is_missing():
    from app.services.storage_service import StorageError

    with pytest.raises(StorageError, match="SUPABASE_SERVICE_ROLE_KEY"):
        _create_app_with({**_SUPABASE, "SUPABASE_SERVICE_ROLE_KEY": ""})


def test_startup_succeeds_with_a_complete_supabase_setup():
    app = _create_app_with(_SUPABASE)
    assert app.config["STORAGE_PROVIDER"] == "supabase"


# ─── Storage keys: random, never the user's filename, never public ────────────

import re
from unittest.mock import MagicMock, call


@pytest.fixture()
def local(tmp_path):
    from app.services.storage_service import LocalStorageBackend
    return LocalStorageBackend(upload_dir=str(tmp_path / "uploads"))


@pytest.mark.parametrize("ext", ["pdf", "docx"])
def test_local_upload_uses_a_random_key_with_the_validated_extension(local, ext):
    result = local.upload(b"data", ext)
    assert re.fullmatch(rf"[0-9a-f]{{32}}\.{ext}", result.key)
    assert result.provider == "local"
    assert local.download_bytes(result.key) == b"data"


def test_local_upload_ignores_anything_but_a_plain_extension(local):
    key = local.upload(b"x", "../../evil").key
    assert "/" not in key and "\\" not in key and ".." not in key


def test_local_keys_are_unique(local):
    assert local.upload(b"a", "pdf").key != local.upload(b"a", "pdf").key


@pytest.mark.parametrize("key", ["../outside.pdf", "a/../../outside.pdf", "/etc/passwd", "C:\Windows\win.ini"])
def test_local_backend_refuses_keys_outside_its_root(local, tmp_path, key):
    from app.services.storage_service import StorageError
    (tmp_path / "outside.pdf").write_bytes(b"secret")
    with pytest.raises(StorageError):
        local.download_bytes(key)
    local.delete(key)
    assert (tmp_path / "outside.pdf").read_bytes() == b"secret"


def test_local_delete_removes_the_file_and_ignores_a_missing_one(local):
    key = local.upload(b"x", "pdf").key
    local.delete(key)
    local.delete(key)
    from app.services.storage_service import StorageError
    with pytest.raises(StorageError):
        local.download_bytes(key)


def test_local_backend_has_no_public_url(local):
    assert local.signed_url(local.upload(b"x", "pdf").key, ttl=300) is None
