"""
config/settings.py calls python-dotenv's load_dotenv() when it is imported, which fills
os.environ from backend/.env. A test session must never do that: a developer's .env can hold
credentials for real services (the Supabase database tests, for one). tests/conftest.py replaces
dotenv.load_dotenv before the app is imported; these tests keep it that way.
"""
import importlib.util
import os
import shutil
from pathlib import Path

import dotenv
import dotenv.main
import pytest

SETTINGS = Path(__file__).resolve().parents[2] / "config" / "settings.py"
SENTINEL = "DOTENV_ISOLATION_SENTINEL"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.delenv(SENTINEL, raising=False)
    path = tmp_path / ".env"
    path.write_text(f"{SENTINEL}=loaded\n")
    return path


def _import_settings_copy_beside(tmp_path):
    """Run a copy of config/settings.py from tmp_path/config/, where its own load_dotenv()
    call finds tmp_path/.env the way the real one finds backend/.env."""
    (tmp_path / "config").mkdir()
    copy = tmp_path / "config" / "settings.py"
    shutil.copy(SETTINGS, copy)
    spec = importlib.util.spec_from_file_location("settings_dotenv_probe", copy)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


def test_load_dotenv_does_nothing_in_the_test_session(env_file):
    loaded = dotenv.load_dotenv(env_file)

    assert loaded is False
    assert SENTINEL not in os.environ


def test_importing_settings_does_not_load_a_dotenv_file(env_file, tmp_path):
    _import_settings_copy_beside(tmp_path)

    assert SENTINEL not in os.environ


def test_the_probe_would_notice_if_load_dotenv_were_live(env_file, tmp_path, monkeypatch):
    monkeypatch.setattr(dotenv, "load_dotenv", dotenv.main.load_dotenv)   # the real function

    _import_settings_copy_beside(tmp_path)

    assert os.environ.get(SENTINEL) == "loaded"
