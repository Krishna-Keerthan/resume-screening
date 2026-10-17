"""
render.yaml is Render's Blueprint file. Render looks for it in the repository root, and a
service's rootDir (default: the repo root) decides where its build and start commands run.
The backend lives in backend/, so the service sets rootDir: backend and runs the same
gunicorn.conf.py the Dockerfile uses.

Field names are the ones in https://render.com/docs/blueprint-spec and
https://render.com/schema/render.yaml.json.
"""
import os

import pytest
import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture(scope="module")
def blueprint():
    with open(os.path.join(_REPO, "render.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def web(blueprint):
    (service,) = [s for s in blueprint["services"] if s["type"] == "web"]
    return service


def test_the_blueprint_is_in_the_repository_root_only():
    assert os.path.isfile(os.path.join(_REPO, "render.yaml"))
    assert not os.path.exists(os.path.join(_REPO, "backend", "render.yaml"))


def test_the_web_service_builds_from_the_backend_directory_with_the_python_runtime(web):
    assert web["runtime"] == "python"
    assert web["rootDir"] == "backend"
    assert "dockerfilePath" not in web and "dockerContext" not in web


def test_the_build_and_start_commands_run_relative_to_the_root_dir(web):
    assert "-r requirements.txt" in web["buildCommand"]
    assert web["startCommand"] == "alembic upgrade head && gunicorn -c gunicorn.conf.py wsgi:app"
    assert os.path.isfile(os.path.join(_REPO, web["rootDir"], "requirements.txt"))
    assert os.path.isfile(os.path.join(_REPO, web["rootDir"], "gunicorn.conf.py"))


def test_the_key_value_store_declares_who_may_connect(blueprint):
    (store,) = [s for s in blueprint["services"] if s["type"] == "keyvalue"]

    assert "ipAllowList" in store      # required by the schema for keyvalue services
