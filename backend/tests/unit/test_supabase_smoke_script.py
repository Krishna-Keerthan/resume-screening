"""
scripts/supabase_smoke_test.py is run by hand against a real Supabase project. These tests
run its logic against the fake server, so the script itself is not untested code: they show
it passes for a private bucket and, more to the point, fails when the bucket is public,
when a signed URL does not expire, and when the service key is wrong. They do not show that
Supabase behaves like the fake; only a real run does (docs/supabase-smoke-test.md).
"""
import importlib.util
import os

import pytest

from tests.unit.fake_supabase import BUCKET, SERVICE_KEY, URL, FakeSupabase

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture(scope="module")
def smoke():
    spec = importlib.util.spec_from_file_location(
        "supabase_smoke_test", os.path.join(_REPO, "scripts", "supabase_smoke_test.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONFIG = {"SUPABASE_URL": URL, "SUPABASE_SERVICE_ROLE_KEY": SERVICE_KEY, "SUPABASE_BUCKET": BUCKET}


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def _run(smoke, fake, clock, *, sleep=None, config=CONFIG):
    lines = []
    ok = smoke.run(config, transport=fake.transport, sleep=sleep or clock.sleep, report=lines.append)
    return ok, lines


def test_it_passes_for_a_private_bucket(smoke):
    clock = Clock()
    fake = FakeSupabase(now=clock)

    ok, lines = _run(smoke, fake, clock)

    assert ok is True
    assert [l[:8] for l in lines] == [f"{n}. PASS " for n in range(1, 7)]
    assert fake.objects == {}                      # it cleaned up after itself


def test_it_prints_neither_the_service_key_nor_a_key_nor_a_signed_url(smoke):
    clock = Clock()
    fake = FakeSupabase(now=clock)

    _, lines = _run(smoke, fake, clock)

    text = "\n".join(lines)
    assert SERVICE_KEY not in text and "token=" not in text and "http" not in text
    assert not any(len(word) == 36 for word in text.split())        # no object key (32 hex + .pdf)


def test_it_fails_when_the_bucket_is_public(smoke):
    clock = Clock()
    fake = FakeSupabase(now=clock)
    fake.public = True

    ok, lines = _run(smoke, fake, clock)

    assert ok is False
    assert lines[0].startswith("1. FAIL") and "private" in lines[0]


def test_it_fails_when_a_signed_url_does_not_expire(smoke):
    clock = Clock()
    fake = FakeSupabase(now=clock)

    ok, lines = _run(smoke, fake, clock, sleep=lambda seconds: None)      # time never passes

    assert ok is False
    assert lines[-1].startswith("5. FAIL") and "expire" in lines[-1]


def test_it_fails_with_a_wrong_service_key(smoke):
    clock = Clock()
    fake = FakeSupabase(now=clock)

    ok, lines = _run(smoke, fake, clock, config={**CONFIG, "SUPABASE_SERVICE_ROLE_KEY": "wrong"})

    assert ok is False
    assert lines[0].startswith("1. FAIL")
    assert "wrong" not in "\n".join(lines)


@pytest.mark.parametrize("missing", list(CONFIG))
def test_a_missing_variable_is_named_and_nothing_is_run(smoke, monkeypatch, missing):
    for name, value in CONFIG.items():
        monkeypatch.setenv(name, "" if name == missing else value)

    with pytest.raises(SystemExit) as stopped:
        smoke.main()

    assert missing in str(stopped.value)
    assert SERVICE_KEY not in str(stopped.value)
