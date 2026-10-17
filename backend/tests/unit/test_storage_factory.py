"""
StorageService.from_config is the one place that picks a backend. Nothing else in the
application branches on the provider's name.
"""
import os
import re

import pytest

from app.services import storage_service
from app.services.storage_service import LocalStorageBackend, StorageError, StorageService

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app")


def test_local_is_the_default(tmp_path):
    for provider in (None, "", "  "):
        backend = StorageService.from_config({"STORAGE_PROVIDER": provider, "UPLOAD_FOLDER": str(tmp_path)})
        assert isinstance(backend, LocalStorageBackend)


def test_the_provider_name_is_case_and_space_insensitive(tmp_path):
    backend = StorageService.from_config({"STORAGE_PROVIDER": "  LOCAL ", "UPLOAD_FOLDER": str(tmp_path)})

    assert isinstance(backend, LocalStorageBackend)


@pytest.mark.parametrize("typo", ["cloudnary", "s3", "supbase"])
def test_an_unknown_provider_stops_startup_instead_of_falling_back_to_local_disk(typo):
    with pytest.raises(StorageError) as stopped:
        StorageService.from_config({"STORAGE_PROVIDER": typo})

    assert typo in str(stopped.value)
    assert "local" in str(stopped.value)       # it lists the valid names


def test_a_backend_is_added_by_registering_a_builder(monkeypatch):
    sentinel = object()
    monkeypatch.setitem(storage_service._BUILDERS, "fake", lambda cfg: sentinel)

    assert StorageService.from_config({"STORAGE_PROVIDER": "fake"}) is sentinel


def test_no_code_outside_the_factory_branches_on_the_provider():
    offenders = []
    for root, _, files in os.walk(_APP):
        for name in files:
            path = os.path.join(root, name)
            if name.endswith(".py") and not path.endswith("storage_service.py"):
                with open(path, encoding="utf-8") as f:
                    for number, line in enumerate(f, 1):
                        if re.search(r"provider\s*(==|!=|\bin\b|\bnot in\b)", line):
                            offenders.append(f"{os.path.relpath(path, _APP)}:{number}: {line.strip()}")

    assert offenders == []
