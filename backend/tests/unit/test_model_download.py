"""
The embedding model is downloaded when the app is built (Render's buildCommand, the
Docker image), not on the first cold start.

scripts/download_model.py loads the model exactly the way EmbeddingService does, from the
same settings (EMBEDDING_MODEL, EMBEDDING_CACHE_DIR), so the cache it fills is the cache
the app reads.
"""
import os
import re
import runpy
import sys
import types

import pytest
import yaml

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_REPO = os.path.dirname(_BACKEND)
_COMMAND = "python -m scripts.download_model"


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def test_the_script_downloads_the_configured_model_into_the_configured_cache(monkeypatch):
    calls = []
    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = lambda *a, **k: calls.append((a, k))
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    monkeypatch.setenv("EMBEDDING_MODEL", "some/model")
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", "/cache/dir")
    monkeypatch.syspath_prepend(_BACKEND)
    for name in ("config", "config.settings", "scripts", "scripts.download_model"):
        monkeypatch.delitem(sys.modules, name, raising=False)   # settings read the env at import

    runpy.run_module("scripts.download_model", run_name="__main__")

    assert calls == [(("some/model",), {"cache_folder": "/cache/dir"})]


def test_render_downloads_the_model_in_the_build_command():
    blueprint = yaml.safe_load(_read(_REPO, "render.yaml"))
    (web,) = [s for s in blueprint["services"] if s["type"] == "web"]

    assert web["buildCommand"].strip().endswith(f"&& {_COMMAND}")


def test_the_docker_image_downloads_the_model_before_the_app_code_is_copied():
    dockerfile = _read(_BACKEND, "Dockerfile")
    pip_install = dockerfile.index("pip install")
    download = dockerfile.index(f"RUN {_COMMAND}")
    copy_everything = dockerfile.index("COPY . .")

    # after the dependencies it needs, before the code that changes often, so the
    # 90 MB layer is rebuilt only when the model, the script or the settings change
    assert pip_install < download < copy_everything
    assert re.search(r"COPY config/? config/", dockerfile)
    assert "COPY scripts/download_model.py" in dockerfile


def test_compose_dev_downloads_the_model_because_its_bind_mount_hides_the_one_in_the_image():
    compose = yaml.safe_load(_read(_REPO, "docker-compose.yml"))
    flask = compose["services"]["flask"]

    assert "./backend:/app" in flask["volumes"]
    # the image sets EMBEDDING_OFFLINE=true, but /app/.cache from the image is not visible here
    assert str(flask["environment"]["EMBEDDING_OFFLINE"]).lower() == "false"
