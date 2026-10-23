"""
A subprocess started by a test imports config/settings.py in a fresh interpreter, where the
conftest replacement of dotenv.load_dotenv does not exist. python-dotenv 1.0.1 has no switch to
turn loading off, and a minimal environment does not stop it: load_dotenv() finds the .env file
itself. These tests check that the environment built for a subprocess keeps .env out.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.subprocess_env import subprocess_env

SETTINGS = Path(__file__).resolve().parents[2] / "config" / "settings.py"
SENTINEL = "SUBPROCESS_ENV_SENTINEL"
_PROBE = f"import os; import config.settings; print(os.environ.get({SENTINEL!r}))"


@pytest.fixture
def project_with_env_file(tmp_path):
    """tmp_path/config/settings.py is a copy of the real file, so its load_dotenv() call finds
    tmp_path/.env the way the real one finds backend/.env."""
    (tmp_path / "config").mkdir()
    shutil.copy(SETTINGS, tmp_path / "config" / "settings.py")
    (tmp_path / ".env").write_text(f"{SENTINEL}=loaded\n")
    return tmp_path


def _run_probe(project, environment):
    return subprocess.run([sys.executable, "-c", _PROBE], cwd=project, env=environment,
                          capture_output=True, text=True, check=True).stdout.strip()


def test_a_value_in_a_dotenv_file_does_not_reach_a_subprocess(project_with_env_file):
    assert _run_probe(project_with_env_file, subprocess_env()) == "None"


def test_a_value_set_by_the_test_still_reaches_the_subprocess(project_with_env_file):
    assert _run_probe(project_with_env_file, subprocess_env(**{SENTINEL: "from-the-test"})) == "from-the-test"


def test_the_probe_would_notice_a_loading_dotenv(project_with_env_file):
    environment = {k: v for k, v in subprocess_env().items() if k != "PYTHONPATH"}   # no guard

    assert _run_probe(project_with_env_file, environment) == "loaded"


def test_the_shell_environment_is_not_inherited(monkeypatch):
    monkeypatch.setenv("SHELL_ONLY_VALUE", "x")

    assert "SHELL_ONLY_VALUE" not in subprocess_env()
