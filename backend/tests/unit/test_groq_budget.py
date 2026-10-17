"""
A request-wide time budget for Groq calls.

POST /applications/ can make two Groq calls in a row (score explanation, then an improvement
plan for low scores). Each is bounded on its own (93 s with the default timeout and retries),
but together they could outlast gunicorn's 115 s. Inside groq_budget(seconds) every attempt's
timeout is capped by the time left, retries stop when it runs out, and an optional call
(the improvement plan) is skipped when too little is left to be worth starting.

The clock is faked: a failing attempt "takes" exactly its timeout, as a real timeout would.
"""
from unittest.mock import MagicMock

import pytest

import app.services.groq_service as groq
from app.services.groq_service import GroqService, groq_budget, remaining_budget


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(groq, "_now", fake)
    monkeypatch.setattr(groq.time, "sleep", fake.sleep)
    return fake


def _service(clock, *, timeout=30, max_retries=2, always_times_out=True):
    service = GroqService(api_key="", timeout=timeout, max_retries=max_retries)
    client = MagicMock()
    answer = MagicMock()
    answer.choices = [MagicMock(message=MagicMock(content='{"plan": ["a"]}'))]

    def create(**kwargs):
        clock.now += kwargs.get("timeout", timeout)       # a timeout takes its whole timeout
        if always_times_out:
            raise TimeoutError("timed out")
        return answer

    client.chat.completions.create.side_effect = create
    service._client, service.available = client, True
    return service, client


def test_there_is_no_budget_outside_groq_budget():
    assert remaining_budget() is None


def test_the_budget_counts_down_and_ends_with_the_block(clock):
    with groq_budget(100):
        assert remaining_budget() == 100
        clock.now += 30
        assert remaining_budget() == 70
    assert remaining_budget() is None


def test_an_attempt_is_not_given_more_time_than_the_budget_has_left(clock):
    service, client = _service(clock, timeout=30, max_retries=0)

    with groq_budget(10):
        service._complete("s", "u")

    assert client.chat.completions.create.call_args.kwargs["timeout"] == 10


def test_without_a_budget_the_sdk_default_timeout_is_untouched(clock):
    service, client = _service(clock, max_retries=0, always_times_out=False)

    service._complete("s", "u")

    assert "timeout" not in client.chat.completions.create.call_args.kwargs


def test_retries_stop_when_the_budget_is_spent(clock):
    service, client = _service(clock, timeout=30, max_retries=5)
    start = clock.now

    with groq_budget(60):
        assert service._complete("s", "u") is None

    assert clock.now - start <= 60
    assert client.chat.completions.create.call_count == 2     # 30 s, wait 1 s, 29 s: spent


def test_a_call_that_fits_uses_its_normal_retries(clock):
    service, client = _service(clock, timeout=30, max_retries=2)
    start = clock.now

    with groq_budget(100):
        service._complete("s", "u")

    assert client.chat.completions.create.call_count == 3
    assert clock.now - start == 93          # the documented worst case for one call


def test_an_exhausted_budget_makes_no_call_at_all(clock):
    service, client = _service(clock)

    with groq_budget(100):
        clock.now += 101
        assert service._complete("s", "u") is None

    client.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("left, runs", [(24, False), (25, True), (60, True)])
def test_the_improvement_plan_is_skipped_when_too_little_budget_is_left(clock, left, runs):
    service, client = _service(clock, max_retries=0, always_times_out=False)
    service.optional_call_min_seconds = 25

    with groq_budget(100):
        clock.now += 100 - left
        result = service.generate_improvement_plan(
            job_title="Engineer", final_score=0.4, missing_skills=[], matched_skills=[],
            experience_years=1.0, required_years=3.0,
        )

    assert client.chat.completions.create.called is runs
    assert result == ({"plan": ["a"]} if runs else {"plan": []})


def test_the_improvement_plan_always_runs_outside_a_budget(clock):
    service, client = _service(clock, max_retries=0, always_times_out=False)

    service.generate_improvement_plan(
        job_title="Engineer", final_score=0.4, missing_skills=[], matched_skills=[],
        experience_years=1.0, required_years=3.0,
    )

    assert client.chat.completions.create.called


# ─── the clock ────────────────────────────────────────────────────────────────

def test_the_budget_follows_the_monotonic_clock():
    import time
    from unittest.mock import patch

    ticks = iter([500.0, 510.0, 525.0])        # entering the block, then two readings

    with patch.object(time, "monotonic", side_effect=lambda: next(ticks)):
        with groq_budget(100):
            assert remaining_budget() == 90.0
            assert remaining_budget() == 75.0


def test_a_wall_clock_that_jumps_back_and_forth_does_not_change_the_budget():
    import itertools
    import time
    from unittest.mock import patch

    # NTP corrections, DST or a VM resume: the wall clock goes back an hour, then forward two.
    jumps = itertools.cycle([1_800_000_000.0, 1_800_000_000.0 - 3600, 1_800_000_000.0 + 3600])

    with patch.object(time, "time", side_effect=lambda: next(jumps)):
        with groq_budget(100):
            first = remaining_budget()
            second = remaining_budget()
            third = remaining_budget()

    assert 99.0 < third <= second <= first <= 100.0       # only ever counts down, by real elapsed time


def test_the_budget_can_start_before_the_block_is_entered(clock):
    with groq_budget(100, already_used=40):
        assert remaining_budget() == 60
