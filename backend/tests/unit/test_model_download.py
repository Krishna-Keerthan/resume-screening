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
from tests.subprocess_env import subprocess_env

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_REPO = os.path.dirname(_BACKEND)
_COMMAND = "python -m scripts.download_model"


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def _run_script(monkeypatch, *, env, loader):
    """Run scripts.download_model with a fake SentenceTransformer; return what it printed/raised."""
    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = loader
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(_BACKEND)
    for name in ("config", "config.settings", "scripts", "scripts.download_model"):
        monkeypatch.delitem(sys.modules, name, raising=False)   # settings read the env at import
    runpy.run_module("scripts.download_model", run_name="__main__")


_INSIDE = os.path.join(_BACKEND, ".cache", "test-embeddings")


def test_the_script_downloads_then_proves_the_cache_works_offline(monkeypatch):
    calls = []

    def loader(*args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(encode=lambda texts, **k: calls.append(("encode", texts)))

    _run_script(monkeypatch, env={"EMBEDDING_MODEL": "some/model", "EMBEDDING_CACHE_DIR": _INSIDE}, loader=loader)

    assert calls[0] == (("some/model",), {"cache_folder": _INSIDE})
    # the second load is exactly how the app loads it in production: local files only
    assert calls[1] == (("some/model",), {"cache_folder": _INSIDE, "local_files_only": True})
    assert calls[2][0] == "encode"


def test_the_script_fails_loudly_if_the_downloaded_cache_cannot_be_loaded_offline(monkeypatch):
    def loader(*args, **kwargs):
        if kwargs.get("local_files_only"):
            raise OSError("incomplete cache")
        return types.SimpleNamespace(encode=lambda *a, **k: None)

    with pytest.raises(SystemExit) as stopped:
        _run_script(monkeypatch, env={"EMBEDDING_CACHE_DIR": _INSIDE}, loader=loader)

    assert "could not be loaded from" in str(stopped.value) and "offline" in str(stopped.value)


def test_the_script_refuses_a_cache_outside_the_project_directory(monkeypatch, tmp_path):
    # Render carries only the project directory from the build to the running service.
    with pytest.raises(SystemExit) as stopped:
        _run_script(monkeypatch, env={"EMBEDDING_CACHE_DIR": str(tmp_path)},
                    loader=lambda *a, **k: pytest.fail("must not download"))

    assert "outside the project directory" in str(stopped.value)


def test_the_cache_path_is_absolute_inside_the_project_and_independent_of_the_working_directory():
    import subprocess

    probe = "from config.settings import BaseConfig, ProductionConfig; print(BaseConfig.EMBEDDING_CACHE_DIR); print(ProductionConfig.EMBEDDING_CACHE_DIR)"
    paths = {
        cwd: subprocess.run([sys.executable, "-c", probe], env=subprocess_env(PYTHONPATH=_BACKEND), cwd=cwd,
                            capture_output=True, text=True, check=True).stdout.split()
        for cwd in (_BACKEND, "/", os.path.join(_BACKEND, "app"))
    }

    expected = os.path.join(_BACKEND, ".cache", "embeddings")
    assert all(p == [expected, expected] for p in paths.values())


def test_the_build_and_the_runtime_read_the_cache_path_from_the_same_setting():
    source = _read(_BACKEND, "scripts", "download_model.py")
    factory = _read(_BACKEND, "app", "services", "service_factory.py")

    assert "BaseConfig.EMBEDDING_CACHE_DIR" in source
    assert 'cfg("EMBEDDING_CACHE_DIR"' in factory


def test_the_cache_path_and_model_name_are_written_in_no_launcher():
    for text in (_read(_REPO, "render.yaml"), _read(_BACKEND, "Dockerfile")):
        assert "all-MiniLM" not in text
        assert ".cache" not in text
        assert "EMBEDDING_CACHE_DIR" not in text


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
