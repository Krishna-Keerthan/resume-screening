"""
Booting the app the way each environment does.

Tables: Alembic builds them in production, create_app() everywhere else. In production the start command runs `alembic upgrade head` before gunicorn. If
the app also called db.create_all(), whichever ran first on an empty database
would win and the other would fail or skip, leaving the schema unmanaged.

Storage: an incomplete Cloudinary setup must stop production from starting
rather than let uploads go somewhere else.

Each case boots the app in a fresh interpreter: create_app() re-initialises the
shared rate limiter and reads settings from the environment at import, so doing
it in the test process would leak into other tests.
"""
import json
import os
import sqlite3
import subprocess
import sys

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

_SCRIPT = """
import json, sys
from unittest.mock import MagicMock, patch
from app.core.database import db

calls = []
real_create_all = db.create_all
db.create_all = lambda *a, **k: (calls.append(1), real_create_all(*a, **k))[1]

from app import create_app
with patch("app.services.service_factory.ServiceFactory.create_all", return_value=MagicMock()):
    create_app(sys.argv[1])
print(json.dumps({"create_all_calls": len(calls)}))
"""


def _run(env_name, database_file, extra_env=None, script=_SCRIPT):
    env = {
        **os.environ,
        "APP_ENV": env_name,
        "DATABASE_URL": f"sqlite:///{database_file}",
        "SECRET_KEY": "x" * 64,
        "RATE_LIMIT_STORAGE_URL": "redis://localhost:1/0",
        **(extra_env or {}),
    }
    return subprocess.run(
        [sys.executable, "-c", script, env_name],
        env=env, capture_output=True, text=True, cwd=_BACKEND_DIR,
    )


def _boot(env_name, database_file):
    out = _run(env_name, database_file)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _tables(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_production_startup_never_calls_create_all(tmp_path):
    result = _boot("production", tmp_path / "prod.db")

    assert result["create_all_calls"] == 0


def test_production_startup_leaves_an_empty_database_empty(tmp_path):
    path = tmp_path / "prod.db"

    _boot("production", path)

    assert not path.exists() or _tables(path) == set()


def test_development_startup_still_creates_the_tables(tmp_path):
    path = tmp_path / "dev.db"

    result = _boot("development", path)

    assert result["create_all_calls"] == 1
    assert {"candidates", "recruiters", "jobs", "resumes"} <= _tables(path)


# ─── File storage ─────────────────────────────────────────────────────────────

_CLOUDINARY = {
    "STORAGE_PROVIDER": "cloudinary",
    "CLOUDINARY_CLOUD_NAME": "demo-cloud",
    "CLOUDINARY_API_KEY": "key-123",
    "CLOUDINARY_API_SECRET": "secret-456",
}


@pytest.mark.parametrize("missing", ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"])
def test_production_refuses_to_start_with_an_incomplete_cloudinary_setup(tmp_path, missing):
    out = _run("production", tmp_path / "prod.db", {**_CLOUDINARY, missing: ""})

    assert out.returncode != 0
    assert "StorageError" in out.stderr
    assert missing in out.stderr
    assert "secret-456" not in out.stderr


def test_production_starts_with_a_complete_cloudinary_setup(tmp_path):
    out = _run("production", tmp_path / "prod.db", _CLOUDINARY)

    assert out.returncode == 0, out.stderr
