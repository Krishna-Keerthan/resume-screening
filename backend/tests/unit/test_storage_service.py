"""
tests/unit/test_storage_service.py  —  backend selection in StorageService.
"""


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
