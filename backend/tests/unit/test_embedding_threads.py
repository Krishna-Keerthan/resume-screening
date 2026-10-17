"""
Torch runs single-threaded: gunicorn --preload loads the model once in the master and
forks workers, and a multi-threaded OpenMP pool created before the fork can deadlock
in the children (and costs memory a 512 MB instance does not have).
"""
import sys
import types
from unittest.mock import MagicMock, patch

from app.services.embedding_service import EmbeddingService


def _fake_libraries(monkeypatch, calls):
    torch = types.ModuleType("torch")
    torch.set_num_threads = lambda n: calls.append(("set_num_threads", n))
    sentence_transformers = types.ModuleType("sentence_transformers")

    def make_model(*args, **kwargs):
        calls.append(("load_model",))
        return MagicMock()

    sentence_transformers.SentenceTransformer = make_model
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)


def test_threads_are_limited_before_the_model_is_loaded(monkeypatch):
    calls = []
    _fake_libraries(monkeypatch, calls)

    service = EmbeddingService(model_name="fake", cache_dir="unused", torch_threads=1)
    assert service._ensure_loaded() is True

    assert calls == [("set_num_threads", 1), ("load_model",)]


def test_the_thread_count_is_configurable(monkeypatch):
    calls = []
    _fake_libraries(monkeypatch, calls)

    EmbeddingService(model_name="fake", cache_dir="unused", torch_threads=3)._ensure_loaded()

    assert ("set_num_threads", 3) in calls


def test_the_factory_passes_the_configured_thread_count(monkeypatch):
    from app.services.service_factory import ServiceFactory

    with patch(
        "app.services.embedding_service.EmbeddingService.get_instance", return_value=MagicMock()
    ) as get_instance:
        ServiceFactory.create_all({
            "TORCH_NUM_THREADS": 2,
            "WEIGHT_SEMANTIC": 0.4, "WEIGHT_KEYWORD": 0.35,
            "WEIGHT_EXPERIENCE": 0.15, "WEIGHT_SECTION_QUALITY": 0.10,
        })

    assert get_instance.call_args.kwargs["torch_threads"] == 2
