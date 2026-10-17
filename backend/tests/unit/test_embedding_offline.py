"""
EMBEDDING_OFFLINE makes the app load the embedding model from the local cache only.

Without it, huggingface_hub asks huggingface.co about every cached file at load time and,
with the network unreachable, retries each request for ~20 s, so a cold start with a baked
model but no network takes minutes. The Docker image and render.yaml turn it on because
the model is downloaded when they are built (scripts/download_model.py, which always
downloads and does not read this setting).
"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from app.services.embedding_service import EmbeddingService


@pytest.fixture()
def model_calls(monkeypatch):
    calls = []
    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = lambda *a, **k: (calls.append((a, k)), MagicMock())[1]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(set_num_threads=lambda n: None))
    return calls


def test_the_model_may_be_fetched_by_default(model_calls):
    EmbeddingService(model_name="m", cache_dir="c")._ensure_loaded()

    assert model_calls[0][1]["local_files_only"] is False


def test_offline_loads_from_the_local_cache_only(model_calls):
    EmbeddingService(model_name="m", cache_dir="c", local_files_only=True)._ensure_loaded()

    assert model_calls == [(("m",), {"cache_folder": "c", "local_files_only": True})]


def test_the_factory_passes_the_offline_setting(app):
    from app.services.service_factory import ServiceFactory

    with patch("app.services.embedding_service.EmbeddingService.get_instance",
               return_value=MagicMock()) as get_instance:
        ServiceFactory.create_all({
            "EMBEDDING_OFFLINE": True,
            "WEIGHT_SEMANTIC": 0.4, "WEIGHT_KEYWORD": 0.35,
            "WEIGHT_EXPERIENCE": 0.15, "WEIGHT_SECTION_QUALITY": 0.10,
        })

    assert get_instance.call_args.kwargs["local_files_only"] is True


def test_the_image_and_the_blueprint_turn_it_on():
    import os
    import yaml

    backend = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    dockerfile = open(os.path.join(backend, "Dockerfile"), encoding="utf-8").read()
    blueprint = yaml.safe_load(open(os.path.join(os.path.dirname(backend), "render.yaml"), encoding="utf-8"))
    (web,) = [s for s in blueprint["services"] if s["type"] == "web"]
    env = {e["key"]: e.get("value") for e in web["envVars"]}

    assert dockerfile.index("RUN python -m scripts.download_model") < dockerfile.index("ENV EMBEDDING_OFFLINE=true")
    assert env["EMBEDDING_OFFLINE"] == "true"
