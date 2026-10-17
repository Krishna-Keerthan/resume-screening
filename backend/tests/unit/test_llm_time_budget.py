"""
llm_time_budget starts the Groq budget when the request started, not when the view started.

gunicorn's 115 s timer runs from the start of the request, so the work done before the view
(authentication, the rate limiter) and any non-Groq work counts against the same 100 s.
"""
import time

import pytest
from flask import g

from app.api.v1._helpers import llm_time_budget
from app.services.groq_service import remaining_budget


@pytest.fixture(autouse=True)
def _clean_g(app):
    """The session app context keeps one `g` for every test: don't leak request_start."""
    with app.test_request_context():
        g.pop("request_start", None)
    yield
    with app.test_request_context():
        g.pop("request_start", None)


@llm_time_budget
def _view():
    return remaining_budget()


def test_time_already_spent_on_the_request_is_taken_off_the_budget(app):
    with app.test_request_context():
        g.request_start = time.perf_counter() - 40

        left = _view()

    assert 59.0 < left <= 60.0


def test_a_request_that_has_just_started_gets_the_whole_budget(app):
    with app.test_request_context():
        g.request_start = time.perf_counter()

        left = _view()

    assert app.config["GROQ_CALL_BUDGET_SECONDS"] - 1 < left <= app.config["GROQ_CALL_BUDGET_SECONDS"]


def test_a_request_that_already_used_the_whole_budget_gets_none(app):
    with app.test_request_context():
        g.request_start = time.perf_counter() - 500

        assert _view() == 0.0


def test_the_budget_still_works_where_the_request_start_was_not_recorded(app):
    with app.test_request_context():
        assert _view() > 90
