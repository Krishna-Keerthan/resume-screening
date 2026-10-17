"""
The .env.example files list every environment variable the code reads, so a new checkout
can be configured from them alone.

Backend: every name read through os.getenv or the _int_env / _float_env / _bool_env /
_list_env / _path_env helpers in the application, its settings, the gunicorn config and the scripts.
Frontend: every process.env.X in the app (NODE_ENV is set by Next.js itself).
"""
import os
import re

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_REPO = os.path.dirname(_BACKEND)

_READ = re.compile(r"""(?:os\.getenv|os\.environ\.get|_int_env|_float_env|_bool_env|_list_env|_path_env)\(\s*["']([A-Z][A-Z0-9_]+)["']""")
_LISTED = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=", re.M)
_FRONTEND_READ = re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)")
_SET_BY_NEXT = {"NODE_ENV"}


def _python_files():
    for folder in ("app", "config", "scripts"):
        for root, _, files in os.walk(os.path.join(_BACKEND, folder)):
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(root, name)
    yield os.path.join(_BACKEND, "gunicorn.conf.py")
    yield os.path.join(_BACKEND, "wsgi.py")
    yield os.path.join(_BACKEND, "run.py")


def _text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _backend_variables_read():
    return {name for path in _python_files() for name in _READ.findall(_text(path))}


def test_backend_example_lists_every_variable_the_backend_reads():
    listed = set(_LISTED.findall(_text(os.path.join(_BACKEND, ".env.example"))))

    assert not _backend_variables_read() - listed


def test_backend_example_lists_nothing_the_backend_does_not_read():
    listed = set(_LISTED.findall(_text(os.path.join(_BACKEND, ".env.example"))))

    assert not listed - _backend_variables_read()


def _frontend_variables_read():
    names = set()
    for folder in ("app", "components", "lib"):
        for root, _, files in os.walk(os.path.join(_REPO, "frontend", folder)):
            for name in files:
                if name.endswith((".ts", ".tsx")):
                    names |= set(_FRONTEND_READ.findall(_text(os.path.join(root, name))))
    for name in ("next.config.js", "middleware.ts"):
        names |= set(_FRONTEND_READ.findall(_text(os.path.join(_REPO, "frontend", name))))
    return names - _SET_BY_NEXT


def test_frontend_example_lists_every_variable_the_frontend_reads():
    listed = set(_LISTED.findall(_text(os.path.join(_REPO, "frontend", ".env.example"))))

    assert _frontend_variables_read() <= listed
    assert "API_PROXY_TARGET" in _frontend_variables_read()      # the scan finds something


def test_the_backend_example_loads_into_a_valid_development_config(tmp_path):
    from dotenv import dotenv_values

    values = {k: v for k, v in dotenv_values(os.path.join(_BACKEND, ".env.example")).items()}
    weights = sum(float(values[k]) for k in (
        "WEIGHT_SEMANTIC", "WEIGHT_KEYWORD", "WEIGHT_EXPERIENCE", "WEIGHT_SECTION_QUALITY"))

    assert weights == pytest.approx(1.0)
    assert values["APP_ENV"] == "development"
    assert values["RATE_LIMIT_STORAGE_URL"].startswith("memory:")
