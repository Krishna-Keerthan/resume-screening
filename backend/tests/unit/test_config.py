
"""
tests/unit/test_config.py

Tests for configuration loading, weight validation, and env resolution.
"""

import pytest
from config import get_config
from config.settings import DevelopmentConfig, ProductionConfig, TestingConfig


def test_get_config_development():
    cfg = get_config("development")
    assert isinstance(cfg, DevelopmentConfig)
    assert cfg.DEBUG is True


def test_get_config_production(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@db:5432/ats")
    monkeypatch.setattr(ProductionConfig, "RATE_LIMIT_STORAGE_URL", "redis://cache:6379/0")
    cfg = get_config("production")
    assert isinstance(cfg, ProductionConfig)
    assert cfg.DEBUG is False
    assert cfg.SQLALCHEMY_DATABASE_URI == "postgresql://user:pw@db:5432/ats"


def test_production_config_requires_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="SECRET_KEY"):
        get_config("production")


def test_production_config_rejects_default_secret_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "dev-secret-change-in-production")
    with pytest.raises(EnvironmentError, match="SECRET_KEY"):
        get_config("production")


def test_get_config_testing():
    cfg = get_config("testing")
    assert isinstance(cfg, TestingConfig)
    assert cfg.TESTING is True


def test_get_config_invalid_raises():
    with pytest.raises(ValueError, match="Unknown environment"):
        get_config("staging_v2_invalid")


def test_weight_sum_sums_to_one():
    cfg = DevelopmentConfig
    total = (
        cfg.WEIGHT_SEMANTIC
        + cfg.WEIGHT_KEYWORD
        + cfg.WEIGHT_EXPERIENCE
        + cfg.WEIGHT_SECTION_QUALITY
    )
    assert 0.99 <= total <= 1.01, f"Weights sum to {total}, expected ~1.0"


def test_testing_config_uses_in_memory_sqlite():
    cfg = TestingConfig
    assert cfg.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"


def test_base_config_has_required_keys():
    from config.settings import BaseConfig
    required = [
        "SECRET_KEY", "UPLOAD_FOLDER", "ALLOWED_EXTENSIONS",
        "EMBEDDING_MODEL", "GROQ_MODEL", "DEFAULT_PAGE_SIZE",
    ]
    for key in required:
        assert hasattr(BaseConfig, key), f"BaseConfig missing key: {key}"

def test_storage_settings_reach_flask_config():
    # Settings are read from the environment at import time, so load them in a
    # fresh interpreter, the same way create_app() does.
    import json
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "STORAGE_PROVIDER":      "cloudinary",
        "CLOUDINARY_CLOUD_NAME": "demo-cloud",
        "CLOUDINARY_API_KEY":    "key-123",
        "CLOUDINARY_API_SECRET": "secret-456",
    }
    script = (
        "import json\n"
        "from flask import Flask\n"
        "from config import get_config\n"
        "app = Flask('probe')\n"
        "app.config.from_object(get_config('development'))\n"
        "keys = ['STORAGE_PROVIDER', 'CLOUDINARY_CLOUD_NAME',\n"
        "        'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET']\n"
        "print(json.dumps({k: app.config.get(k) for k in keys}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True,
        check=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "STORAGE_PROVIDER":      "cloudinary",
        "CLOUDINARY_CLOUD_NAME": "demo-cloud",
        "CLOUDINARY_API_KEY":    "key-123",
        "CLOUDINARY_API_SECRET": "secret-456",
    }


@pytest.mark.parametrize("url", ["memory://", "memory:", "memory://anything"])
def test_production_config_refuses_per_process_rate_limit_storage(monkeypatch, url):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setattr(ProductionConfig, "RATE_LIMIT_STORAGE_URL", url)
    with pytest.raises(EnvironmentError, match="RATE_LIMIT_STORAGE_URL"):
        get_config("production")


def test_production_config_accepts_a_shared_rate_limit_store(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setattr(ProductionConfig, "RATE_LIMIT_STORAGE_URL", "redis://cache:6379/0")
    assert get_config("production").RATE_LIMIT_STORAGE_URL == "redis://cache:6379/0"



# ─── proxy and cookie settings ────────────────────────────────────────────────

_PROXY_KEYS = ("TRUSTED_PROXY_HOPS", "LOG_PROXY_CHAIN", "REFRESH_COOKIE_SECURE")


def _read_settings(env_name, overrides):
    """Read the proxy/cookie settings in a fresh interpreter: they are read from the environment at import."""
    import json
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in _PROXY_KEYS}
    env.update({
        "SECRET_KEY": "x" * 64,
        "DATABASE_URL": "postgresql://u:p@db/ats",
        "RATE_LIMIT_STORAGE_URL": "redis://cache:6379/0",
        **overrides,
    })
    script = (
        "import json\n"
        "from config import get_config\n"
        f"cfg = get_config({env_name!r})\n"
        f"print(json.dumps({{k: getattr(cfg, k) for k in {list(_PROXY_KEYS)!r}}}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True,
        check=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("env_name, hops, secure", [
    ("development", 0, False),
    ("production", 2, True),
    ("testing", 2, False),
])
def test_proxy_and_cookie_defaults_per_environment(env_name, hops, secure):
    assert _read_settings(env_name, {}) == {
        "TRUSTED_PROXY_HOPS": hops, "LOG_PROXY_CHAIN": False, "REFRESH_COOKIE_SECURE": secure,
    }


def test_production_reads_the_hop_count_and_the_cookie_flag_from_the_environment():
    got = _read_settings(
        "production",
        {"TRUSTED_PROXY_HOPS": "3", "LOG_PROXY_CHAIN": "true", "REFRESH_COOKIE_SECURE": "false"},
    )
    assert got == {"TRUSTED_PROXY_HOPS": 3, "LOG_PROXY_CHAIN": True, "REFRESH_COOKIE_SECURE": False}
