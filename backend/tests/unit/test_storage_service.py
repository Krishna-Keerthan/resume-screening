"""
tests/unit/test_storage_service.py  —  backend selection in StorageService.
"""
from unittest.mock import patch

import pytest


def test_cloudinary_backend_selected_when_configured():
    from app.services.storage_service import CloudinaryStorageBackend, StorageService

    backend = StorageService.from_config({
        "STORAGE_PROVIDER":      "cloudinary",
        "CLOUDINARY_CLOUD_NAME": "demo-cloud",
        "CLOUDINARY_API_KEY":    "key-123",
        "CLOUDINARY_API_SECRET": "secret-456",
    })
    assert isinstance(backend, CloudinaryStorageBackend)
    assert backend.provider == "cloudinary"


def test_local_backend_is_default(tmp_path):
    from app.services.storage_service import LocalStorageBackend, StorageService

    backend = StorageService.from_config({"UPLOAD_FOLDER": str(tmp_path)})
    assert isinstance(backend, LocalStorageBackend)


_CLOUDINARY = {
    "STORAGE_PROVIDER":      "cloudinary",
    "CLOUDINARY_CLOUD_NAME": "demo-cloud",
    "CLOUDINARY_API_KEY":    "key-123",
    "CLOUDINARY_API_SECRET": "secret-456",
}


@pytest.mark.parametrize("missing", [
    "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET",
])
def test_incomplete_cloudinary_config_raises(missing):
    from app.services.storage_service import StorageError, StorageService

    config = {**_CLOUDINARY, missing: ""}
    with pytest.raises(StorageError, match=missing):
        StorageService.from_config(config)


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


def test_startup_fails_when_cloudinary_credentials_missing():
    from app.services.storage_service import StorageError

    with pytest.raises(StorageError, match="CLOUDINARY_API_SECRET"):
        _create_app_with({**_CLOUDINARY, "CLOUDINARY_API_SECRET": ""})


def test_startup_succeeds_with_complete_cloudinary_credentials():
    app = _create_app_with(_CLOUDINARY)
    assert app.config["STORAGE_PROVIDER"] == "cloudinary"


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
    assert not hasattr(local, "signed_url")


@pytest.fixture()
def cloud():
    from app.services.storage_service import CloudinaryStorageBackend
    with patch("cloudinary.config"):
        return CloudinaryStorageBackend("demo", "key", "secret", folder="resumes")


def test_cloudinary_upload_is_authenticated_raw_with_a_random_public_id(cloud):
    with patch("cloudinary.uploader.upload") as upload:
        upload.return_value = {"public_id": "resumes/abc.pdf", "bytes": 2048,
                               "secure_url": "https://res.cloudinary.com/demo/raw/upload/resumes/abc.pdf"}
        result = cloud.upload(b"%PDF-1.4", "pdf")

    args, kwargs = upload.call_args
    assert args == (b"%PDF-1.4",)
    public_id = kwargs.pop("public_id")
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", public_id)
    assert kwargs == {
        "resource_type": "raw", "type": "authenticated", "folder": "resumes",
        "use_filename": False, "unique_filename": False, "overwrite": False, "tags": ["resume"],
    }
    assert result.key == "resumes/abc.pdf"
    assert result.size_kb == 2
    assert result.provider == "cloudinary"
    assert not hasattr(result, "url")


def test_cloudinary_upload_failure_raises_storage_error(cloud):
    from app.services.storage_service import StorageError
    with patch("cloudinary.uploader.upload", side_effect=RuntimeError("boom")):
        with pytest.raises(StorageError):
            cloud.upload(b"x", "pdf")


def test_cloudinary_delete_passes_the_authenticated_raw_kwargs(cloud):
    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
        cloud.delete("resumes/abc.pdf")
    assert destroy.call_args_list == [call("resumes/abc.pdf", resource_type="raw", type="authenticated")]


def test_cloudinary_signed_url_expires_after_the_ttl(cloud):
    with patch("time.time", return_value=1_000_000.9), \
         patch("cloudinary.utils.private_download_url", return_value="https://signed") as sign:
        url = cloud.signed_url("resumes/abc.pdf", ttl=300)
    assert url == "https://signed"
    assert sign.call_args_list == [
        call("resumes/abc.pdf", "", resource_type="raw", type="authenticated", expires_at=1_000_300)
    ]


def test_cloudinary_download_bytes_fetches_a_signed_url(cloud):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b"%PDF-1.4"
    with patch.object(type(cloud), "signed_url", return_value="https://signed") as sign, \
         patch("urllib.request.urlopen", return_value=response) as urlopen:
        assert cloud.download_bytes("resumes/abc.pdf") == b"%PDF-1.4"
    sign.assert_called_once()
    assert urlopen.call_args.args[0] == "https://signed"
