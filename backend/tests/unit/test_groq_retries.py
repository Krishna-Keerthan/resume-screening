"""
GROQ_MAX_RETRIES and GROQ_TIMEOUT_SECONDS decide how long one Groq call can take.

The chain of timeouts is axios 110 s < gunicorn 115 s < Vercel's proxy 120 s, and
one call must finish well inside it: its worst case stays under
GROQ_CALL_BUDGET_SECONDS (100 s).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.groq_service import GroqService, worst_case_seconds
from tests.unit.test_production_startup import _run


def _service(max_retries, failures):
    """A GroqService whose client fails `failures` times, then answers."""
    service = GroqService(api_key="", max_retries=max_retries)
    client = MagicMock()
    answer = MagicMock()
    answer.choices = [MagicMock(message=MagicMock(content="ok"))]
    client.chat.completions.create.side_effect = [RuntimeError("boom")] * failures + [answer]
    service._client = client
    service.available = True
    return service, client


@pytest.mark.parametrize("max_retries", [0, 1, 2, 4])
def test_a_failing_call_is_attempted_once_plus_max_retries_times(max_retries):
    service, client = _service(max_retries, failures=99)

    with patch("app.services.groq_service.time.sleep"):
        assert service._complete("system", "user") is None

    assert client.chat.completions.create.call_count == max_retries + 1


def test_the_wait_between_attempts_doubles_and_is_not_applied_after_the_last_one():
    service, _ = _service(3, failures=99)

    with patch("app.services.groq_service.time.sleep") as sleep:
        service._complete("system", "user")

    assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0, 4.0]


def test_a_call_that_succeeds_after_retries_returns_the_answer():
    service, client = _service(2, failures=2)

    with patch("app.services.groq_service.time.sleep"):
        assert service._complete("system", "user") == "ok"

    assert client.chat.completions.create.call_count == 3


def test_the_sdk_does_not_retry_on_top_of_ours():
    with patch("groq.Groq") as groq_client:
        GroqService(api_key="gsk_test", timeout=25, max_retries=2)

    assert groq_client.call_args.kwargs["max_retries"] == 0
    assert groq_client.call_args.kwargs["timeout"] == 25


@pytest.mark.parametrize("timeout, retries, expected", [
    (30, 0, 30.0),
    (30, 2, 93.0),     # 3 x 30 s + 1 s + 2 s of waiting
    (30, 3, 127.0),    # 4 x 30 s + 1 s + 2 s + 4 s
    (10, 4, 65.0),     # 5 x 10 s + 1 + 2 + 4 + 8
])
def test_worst_case_is_every_attempt_timing_out_plus_all_the_waiting(timeout, retries, expected):
    assert worst_case_seconds(timeout, retries) == expected


def test_the_default_settings_stay_under_the_call_budget():
    from config.settings import BaseConfig

    assert BaseConfig.GROQ_MAX_RETRIES == 2
    assert worst_case_seconds(BaseConfig.GROQ_TIMEOUT_SECONDS, BaseConfig.GROQ_MAX_RETRIES) \
        < BaseConfig.GROQ_CALL_BUDGET_SECONDS == 100


def test_the_factory_passes_the_configured_retries_to_the_service(app):
    from app.services.service_factory import ServiceFactory

    with patch("app.services.embedding_service.EmbeddingService.get_instance",
               return_value=MagicMock()),          patch("app.services.groq_service.GroqService") as groq_cls:
        ServiceFactory.create_all({
            "GROQ_MAX_RETRIES": 1, "GROQ_TIMEOUT_SECONDS": 20,
            "WEIGHT_SEMANTIC": 0.4, "WEIGHT_KEYWORD": 0.35,
            "WEIGHT_EXPERIENCE": 0.15, "WEIGHT_SECTION_QUALITY": 0.10,
        })

    assert groq_cls.call_args.kwargs["max_retries"] == 1
    assert groq_cls.call_args.kwargs["timeout"] == 20


def test_production_refuses_to_start_when_retries_could_outlast_the_budget(tmp_path):
    out = _run("production", tmp_path / "prod.db", {"GROQ_MAX_RETRIES": "3", "GROQ_TIMEOUT_SECONDS": "30"})

    assert out.returncode != 0
    assert "GROQ" in out.stderr and "127s" in out.stderr
