
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