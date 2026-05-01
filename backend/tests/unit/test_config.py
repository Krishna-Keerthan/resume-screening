
"""
tests/unit/test_config.py

Tests for configuration loading, weight validation, and env resolution.
"""

import pytest
from config import get_config
from config.settings import DevelopmentConfig, ProductionConfig, TestingConfig


def test_get_config_development():
    cfg = get_config("development")
    assert cfg is DevelopmentConfig
    assert cfg.DEBUG is True


def test_get_config_production():
    cfg = get_config("production")
    assert cfg is ProductionConfig
    assert cfg.DEBUG is False


def test_get_config_testing():
    cfg = get_config("testing")
    assert cfg is TestingConfig
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