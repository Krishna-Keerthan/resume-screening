"""
How the server is started: one entry point (wsgi:app), one gunicorn config, one timeout.

Docker, the Procfile and render.yaml all run `gunicorn -c gunicorn.conf.py wsgi:app`;
workers, timeout, bind address and log level live in config/settings.py and reach
gunicorn through gunicorn.conf.py, so no launcher can drift from another.

The timeout chain, innermost first: one Groq call (100 s budget) < axios (110 s)
< gunicorn (115 s) < Vercel's proxy (120 s).
"""
import json
import os
import re
import subprocess
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_REPO = os.path.dirname(_BACKEND)
_VERCEL_PROXY_TIMEOUT_SECONDS = 120


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def _launch_commands():
    procfile = next(l for l in _read(_BACKEND, "Procfile").splitlines() if l.startswith("web:"))
    render = re.search(r"startCommand:\s*(.+)", _read(_BACKEND, "render.yaml")).group(1)
    docker_cmd = re.search(r"^CMD\s+(\[.*\])\s*$", _read(_BACKEND, "Dockerfile"), re.M).group(1)
    return {
        "Procfile": procfile,
        "render.yaml": render,
        "Dockerfile": " ".join(json.loads(docker_cmd)),
    }


@pytest.mark.parametrize("launcher", ["Procfile", "render.yaml", "Dockerfile"])
def test_every_launcher_runs_wsgi_app_with_the_shared_gunicorn_config(launcher):
    command = _launch_commands()[launcher]

    assert "gunicorn -c gunicorn.conf.py wsgi:app" in command
    assert "run:app" not in command


@pytest.mark.parametrize("launcher", ["Procfile", "render.yaml", "Dockerfile"])
@pytest.mark.parametrize("flag", ["--timeout", "--workers", "--bind", "--log-level", "--preload"])
def test_no_launcher_repeats_a_setting_that_the_config_owns(launcher, flag):
    assert flag not in _launch_commands()[launcher]


_PROBE = """
import json, os, runpy
conf = runpy.run_path("gunicorn.conf.py")
keys = ("bind", "workers", "timeout", "preload_app", "loglevel")
print(json.dumps({**{k: conf[k] for k in keys}, "omp": os.environ.get("OMP_NUM_THREADS")}))
"""


def _gunicorn_conf(**env):
    base = {k: v for k, v in os.environ.items()
            if k not in ("WORKERS", "PORT", "HOST", "LOG_LEVEL", "OMP_NUM_THREADS",
                         "GUNICORN_TIMEOUT_SECONDS", "TORCH_NUM_THREADS")}
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env={**base, "APP_ENV": "development", **env},
        capture_output=True, text=True, cwd=_BACKEND, check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_gunicorn_reads_its_settings_from_config():
    conf = _gunicorn_conf(WORKERS="3", GUNICORN_TIMEOUT_SECONDS="111", PORT="7777", LOG_LEVEL="ERROR")

    assert (conf["workers"], conf["timeout"], conf["bind"], conf["loglevel"]) == (3, 111, "0.0.0.0:7777", "error")


def test_gunicorn_preloads_the_app_so_the_model_loads_once():
    assert _gunicorn_conf()["preload_app"] is True


@pytest.mark.parametrize("env, expected", [({}, "1"), ({"TORCH_NUM_THREADS": "2"}, "2")])
def test_openmp_threads_are_set_before_the_app_is_imported(env, expected):
    assert _gunicorn_conf(**env)["omp"] == expected


def _client_timeout_seconds():
    source = _read(_REPO, "frontend", "lib", "api", "client.ts")
    millis = int(re.search(r"timeout:\s*([\d_]+)", source).group(1).replace("_", ""))
    return millis / 1000


def test_each_timeout_is_shorter_than_the_one_outside_it():
    from config.settings import BaseConfig

    assert BaseConfig.GROQ_CALL_BUDGET_SECONDS < _client_timeout_seconds()
    assert _client_timeout_seconds() < BaseConfig.GUNICORN_TIMEOUT_SECONDS
    assert BaseConfig.GUNICORN_TIMEOUT_SECONDS < _VERCEL_PROXY_TIMEOUT_SECONDS


def test_the_default_gunicorn_timeout_is_115_seconds():
    from config.settings import BaseConfig

    assert BaseConfig.GUNICORN_TIMEOUT_SECONDS == 115
