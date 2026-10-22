"""
scripts/run_supabase_check.sh reads backend/.env without sourcing it. These tests run the real
script with a stand-in for the Python interpreter that reports which T_* variables reached
it (as JSON), so what the child process receives is checked exactly. Every value here is a
made-up string; nothing reads a real .env.
"""
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_supabase_check.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

REPORTER = """import json, os
print(json.dumps({k: v for k, v in os.environ.items() if k.startswith("T_")}))
"""


@pytest.fixture
def run(tmp_path):
    reporter = tmp_path / "reporter.py"
    reporter.write_text(REPORTER)
    fake_python = tmp_path / "fake_python"
    fake_python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{reporter}"\n')
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)

    def _run(content: bytes, check: str = "storage"):
        env_file = tmp_path / "env"
        env_file.write_bytes(content)
        env = {"PATH": "/usr/bin:/bin", "ENV_FILE": str(env_file), "PYTHON": str(fake_python), "HOME": str(tmp_path)}
        done = subprocess.run(["bash", str(SCRIPT), check], env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return _run


def test_crlf_line_endings_do_not_reach_the_values(run):
    got = run(b"T_A=abc\r\nT_B=def\r\n")

    assert got == {"T_A": "abc", "T_B": "def"}


def test_a_value_may_contain_equals_signs(run):
    assert run(b"T_A=a=b==c\n") == {"T_A": "a=b==c"}


def test_surrounding_quotes_are_removed_and_the_inside_is_literal(run):
    got = run(b'T_D="x y=z"\nT_S=\'p&q$HOME\'\n')

    assert got == {"T_D": "x y=z", "T_S": "p&q$HOME"}


def test_an_export_prefix_is_accepted(run):
    got = run(b'export T_A=abc\nexport   T_B="q r"\n')

    assert got == {"T_A": "abc", "T_B": "q r"}


def test_comment_and_blank_lines_are_ignored(run):
    got = run(b"# T_A=no\n\n   # T_B=no\nT_C=yes\n")

    assert got == {"T_C": "yes"}


def test_empty_values_are_set_and_empty(run):
    got = run(b'T_A=\nT_B=""\nT_C=\'\'\n')

    assert got == {"T_A": "", "T_B": "", "T_C": ""}


def test_a_utf8_byte_order_mark_at_the_start_of_the_file_is_ignored(run):
    got = run(b"\xef\xbb\xbfT_A=abc\r\nT_B=def\r\n")

    assert got == {"T_A": "abc", "T_B": "def"}


def test_a_last_line_without_a_newline_is_read(run):
    assert run(b"T_A=abc\nT_B=last") == {"T_A": "abc", "T_B": "last"}


def test_values_are_never_executed_or_expanded(run, tmp_path):
    marker = tmp_path / "ran"
    got = run(f"T_A=p&w$HOME`touch {marker}`$(touch {marker})#x=y\n".encode())

    assert not marker.exists()
    assert got == {"T_A": f"p&w$HOME`touch {marker}`$(touch {marker})#x=y"}
