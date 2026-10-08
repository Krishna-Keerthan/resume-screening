"""
tests/unit/test_service_factory.py  —  ServiceFactory wiring.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest


def test_ats_weights_come_from_weight_settings(app):
    from app.services.service_factory import ServiceFactory

    config = {
        "WEIGHT_SEMANTIC":        0.10,
        "WEIGHT_KEYWORD":         0.60,
        "WEIGHT_EXPERIENCE":      0.20,
        "WEIGHT_SECTION_QUALITY": 0.10,
    }
    with patch("app.services.embedding_service.EmbeddingService.get_instance",
               return_value=MagicMock()):
        services = ServiceFactory.create_all(config)

    assert services.ats_scorer._weights == {
        "semantic": 0.10, "keyword": 0.60, "experience": 0.20, "section": 0.10,
    }


def test_build_repos_does_not_fall_back_to_mocks(monkeypatch):
    from app.services.service_factory import _build_repos

    monkeypatch.setitem(sys.modules, "app.repositories", None)
    with pytest.raises(ImportError):
        _build_repos()
