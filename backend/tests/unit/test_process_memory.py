"""
Resident memory of the process, logged at startup, when a worker starts and after each
scoring, so the first deploy reports real numbers against Render's 512 MB.

The line is INFO on its own logger and appears even at LOG_LEVEL=WARNING, which is what
production uses. It carries the pid, the stage and the RSS in MB, nothing else.
"""
import json
import logging
import os
import subprocess
import sys

import pytest

from app.core.process_memory import log_rss, rss_mb
from tests.unit.test_production_startup import _BACKEND_DIR, _run


@pytest.fixture()
def captured():
    """Collect every record that reaches the root logger's handlers, whatever LOG_LEVEL is."""
    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    root = logging.getLogger()
    handler, level = _Collect(), root.level
    root.addHandler(handler)
    root.setLevel(logging.WARNING)          # production's level
    yield records
    root.removeHandler(handler)
    root.setLevel(level)


def _memory_records(records):
    return [r for r in records if r.name == "app.memory"]


def test_rss_is_read_from_the_proc_status_file(tmp_path):
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmPeak:\t  999999 kB\nVmRSS:\t  123456 kB\nThreads:\t1\n")

    assert rss_mb(status) == pytest.approx(120.6, abs=0.1)


def test_rss_is_none_when_proc_is_not_available(tmp_path):
    assert rss_mb(tmp_path / "missing") is None


@pytest.mark.skipif(not os.path.exists("/proc/self/status"), reason="needs Linux /proc")
def test_rss_of_this_process_is_positive():
    assert rss_mb() > 10


def test_log_rss_emits_info_even_when_the_root_level_is_warning(captured):
    log_rss("startup")

    (record,) = _memory_records(captured)
    assert record.levelno == logging.INFO
    assert (record.stage, record.pid) == ("startup", os.getpid())
    assert record.rss_mb > 0


def test_nothing_is_logged_when_rss_cannot_be_read(captured, monkeypatch):
    monkeypatch.setattr("app.core.process_memory.rss_mb", lambda *a, **k: None)

    log_rss("startup")

    assert _memory_records(captured) == []


def test_each_scoring_logs_the_memory_it_ended_with(ats_scorer, captured):
    ats_scorer.score_raw(
        resume_text="Python developer with Flask and PostgreSQL experience.",
        resume_skills=["python", "flask"], resume_experience=[], resume_education=[],
        resume_experience_years=3.0, job_title="Backend Engineer",
        job_description="Build services in Python.", job_required_skills=["python"],
    )

    (record,) = _memory_records(captured)
    assert record.stage == "scored"


def test_production_startup_logs_the_memory_at_warning_level(tmp_path):
    out = _run("production", tmp_path / "prod.db", {"LOG_LEVEL": "WARNING"})

    assert out.returncode == 0, out.stderr
    lines = [json.loads(l) for l in out.stdout.splitlines() if l.startswith("{") and "Process memory" in l]
    assert [l["extra"]["stage"] for l in lines] == ["startup"]
    assert lines[0]["extra"]["rss_mb"] > 0


_HOOK_PROBE = """
import runpy
from app.core.logging import configure_logging
configure_logging("WARNING", "json")
runpy.run_path("gunicorn.conf.py")["post_fork"](None, None)
"""


def test_gunicorn_logs_the_memory_of_each_worker_after_the_fork():
    out = subprocess.run(
        [sys.executable, "-c", _HOOK_PROBE],
        env={**os.environ, "APP_ENV": "development"}, capture_output=True, text=True,
        cwd=_BACKEND_DIR, check=True,
    )

    lines = [json.loads(l) for l in out.stdout.splitlines() if l.startswith("{") and "Process memory" in l]
    assert [l["extra"]["stage"] for l in lines] == ["worker_start"]
