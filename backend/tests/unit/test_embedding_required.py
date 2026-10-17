"""
With EMBEDDING_OFFLINE=true the model must already be in the cache (it is downloaded when the
app is built). If it is not, the app refuses to start rather than run without semantic
scoring: the score would silently lose its 40 % semantic component.
"""
import sys
from types import SimpleNamespace

import pytest
from flask import Flask

from app import _require_embedding_model
from tests.unit.test_production_startup import _run

_BOOT_WITH_THE_REAL_SERVICES = """
import sys
from app import create_app
create_app(sys.argv[1])
"""


def _app(*, offline, embedding_available=None, services="present"):
    app = Flask(__name__)
    app.config.update(EMBEDDING_OFFLINE=offline, EMBEDDING_MODEL="the/model", EMBEDDING_CACHE_DIR="/the/cache")
    if services == "present":
        app.extensions["services"] = SimpleNamespace(embedding=SimpleNamespace(available=embedding_available))
    else:
        app.extensions["services"] = None
    return app


def test_offline_with_the_model_missing_stops_startup_with_a_clear_error():
    with pytest.raises(RuntimeError) as stopped:
        _require_embedding_model(_app(offline=True, embedding_available=False))

    message = str(stopped.value)
    assert "EMBEDDING_OFFLINE" in message
    assert "the/model" in message and "/the/cache" in message
    assert "python -m scripts.download_model" in message


def test_offline_with_the_service_layer_down_also_stops_startup():
    with pytest.raises(RuntimeError, match="EMBEDDING_OFFLINE"):
        _require_embedding_model(_app(offline=True, services=None))


def test_offline_with_the_model_loaded_starts():
    _require_embedding_model(_app(offline=True, embedding_available=True))


def test_online_without_the_model_still_starts_and_is_reported_by_health():
    # development: the first run downloads it; if it cannot, /health/services says so
    _require_embedding_model(_app(offline=False, embedding_available=False))


def test_production_refuses_to_boot_offline_with_an_empty_model_cache(tmp_path):
    cache = tmp_path / "empty-cache"
    out = _run("production", tmp_path / "prod.db", {
        "EMBEDDING_OFFLINE": "true", "EMBEDDING_CACHE_DIR": str(cache), "EMBEDDING_MODEL": "all-MiniLM-L6-v2",
    }, script=_BOOT_WITH_THE_REAL_SERVICES)

    assert out.returncode != 0
    assert "EMBEDDING_OFFLINE" in out.stderr and str(cache) in out.stderr
