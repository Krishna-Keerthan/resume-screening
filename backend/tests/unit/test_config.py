
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
