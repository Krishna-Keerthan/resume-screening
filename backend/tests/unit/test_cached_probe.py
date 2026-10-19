"""CachedProbe: a yes/no check whose answer is reused for a while, on an injectable clock."""
import pytest

from app.utils.cached_probe import CachedProbe


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _probe(results, ttl=30.0):
    clock, calls = Clock(), []

    def check():
        calls.append(clock.now)
        value = results[min(len(calls), len(results)) - 1]
        if isinstance(value, Exception):
            raise value
        return value

    return CachedProbe(check, ttl, clock=clock), clock, calls


def test_the_first_call_runs_the_check():
    probe, _, calls = _probe([True])

    assert probe() is True
    assert len(calls) == 1


def test_calls_within_the_ttl_reuse_the_answer():
    probe, clock, calls = _probe([True, False])

    probe()
    clock.now += 29.9

    assert probe() is True
    assert len(calls) == 1


def test_a_call_after_the_ttl_runs_the_check_again():
    probe, clock, calls = _probe([True, False])

    probe()
    clock.now += 30.0

    assert probe() is False
    assert len(calls) == 2


def test_a_failed_check_is_reused_too():
    probe, clock, calls = _probe([False, True])

    probe()
    clock.now += 5

    assert probe() is False
    assert len(calls) == 1


def test_a_zero_ttl_never_reuses_an_answer():
    probe, _, calls = _probe([True], ttl=0)

    probe()
    probe()

    assert len(calls) == 2


def test_an_exception_is_not_cached():
    probe, _, calls = _probe([RuntimeError("down"), True])

    with pytest.raises(RuntimeError):
        probe()

    assert probe() is True
    assert len(calls) == 2
