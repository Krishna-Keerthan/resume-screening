"""
How the server is started: one entry point (wsgi:app), one gunicorn config, one timeout.

Docker and the Procfile run backend/start.sh (`alembic upgrade head`, then
`gunicorn -c gunicorn.conf.py wsgi:app`), and render.yaml runs the Dockerfile's CMD;
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
import yaml
from tests.subprocess_env import subprocess_env

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_REPO = os.path.dirname(_BACKEND)
_VERCEL_PROXY_TIMEOUT_SECONDS = 120


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def _launch_commands():
    procfile = next(l for l in _read(_BACKEND, "Procfile").splitlines() if l.startswith("web:"))
    docker_cmd = re.search(r"^CMD\s+(\[.*\])\s*$", _read(_BACKEND, "Dockerfile"), re.M).group(1)
    return {
        "Procfile": procfile.removeprefix("web:").strip(),
        "Dockerfile": " ".join(json.loads(docker_cmd)),
    }


def test_the_start_script_migrates_then_hands_the_process_to_gunicorn():
    lines = [l.strip() for l in _read(_BACKEND, "start.sh").splitlines() if l.strip() and not l.startswith("#")]

    assert lines == [
        "set -e",
        "alembic upgrade head",
        "exec gunicorn -c gunicorn.conf.py wsgi:app",
    ]


@pytest.mark.parametrize("launcher", ["Procfile", "Dockerfile"])
def test_every_launcher_runs_the_one_start_script(launcher):
    assert _launch_commands()[launcher] == "sh start.sh"


def test_render_yaml_does_not_repeat_the_start_command():
    blueprint = yaml.safe_load(_read(_REPO, "render.yaml"))
    (web,) = [s for s in blueprint["services"] if s["type"] == "web"]

    for field in ("startCommand", "dockerCommand", "preDeployCommand", "buildCommand"):
        assert field not in web


@pytest.mark.parametrize("flag", ["--timeout", "--workers", "--bind", "--log-level", "--preload"])
def test_the_start_script_repeats_no_setting_that_the_config_owns(flag):
    assert flag not in _read(_BACKEND, "start.sh")


_PROBE = """
import json, os, runpy
conf = runpy.run_path("gunicorn.conf.py")
keys = ("bind", "workers", "timeout", "preload_app", "loglevel")
print(json.dumps({**{k: conf[k] for k in keys}, "omp": os.environ.get("OMP_NUM_THREADS")}))
"""


def _gunicorn_conf(**env):
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=subprocess_env(APP_ENV="development", **env),
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
