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
