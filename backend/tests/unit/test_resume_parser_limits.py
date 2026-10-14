"""The parser bounds how long it runs and how much text it keeps."""
import time
from unittest.mock import patch

from app.services.resume_parser import ParseResult, ResumeParserService


def test_a_parse_that_runs_past_the_timeout_fails_cleanly():
    parser = ResumeParserService(parse_timeout_seconds=0.2)

    def slow(self, path):
        time.sleep(2)
        return ParseResult(raw_text="late", parse_error=None)

    with patch.object(ResumeParserService, "parse", slow):
        started = time.monotonic()
        result = parser.parse_bytes(b"%PDF-1.4", "resume.pdf")

    assert time.monotonic() - started < 1.5
    assert result.success is False
    assert "timed out" in result.parse_error


def test_a_parse_inside_the_timeout_is_returned_unchanged():
    parser = ResumeParserService(parse_timeout_seconds=5)
    expected = ParseResult(raw_text="Python developer", parse_error=None)
    with patch.object(ResumeParserService, "parse", lambda self, path: expected):
        assert parser.parse_bytes(b"%PDF-1.4", "resume.pdf") is expected


def test_an_exception_in_the_worker_propagates_like_before():
    parser = ResumeParserService(parse_timeout_seconds=5)

    def boom(self, path):
        raise RuntimeError("bad pdf")

    with patch.object(ResumeParserService, "parse", boom):
        try:
            parser.parse_bytes(b"%PDF-1.4", "resume.pdf")
        except RuntimeError as exc:
            assert "bad pdf" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")


def test_extracted_text_is_capped():
    parser = ResumeParserService(max_text_chars=1000)
    with patch.object(ResumeParserService, "_extract_pdf", return_value="python developer " * 5000):
        result = parser.parse_bytes(b"%PDF-1.4", "resume.pdf")
    assert result.success
    assert len(result.raw_text) <= 1000


def test_text_under_the_cap_is_kept_whole():
    parser = ResumeParserService(max_text_chars=1000)
    with patch.object(ResumeParserService, "_extract_pdf", return_value="python developer"):
        assert parser.parse_bytes(b"%PDF-1.4", "resume.pdf").raw_text == "python developer"


def test_the_factory_passes_the_configured_limits_to_the_parser():
    from unittest.mock import MagicMock

    from app.services.service_factory import ServiceFactory

    with patch("app.services.embedding_service.EmbeddingService.get_instance", return_value=MagicMock()):
        services = ServiceFactory.create_all({
            "PARSE_TIMEOUT_SECONDS": 7, "MAX_PARSED_TEXT_CHARS": 1234,
            "WEIGHT_SEMANTIC": 0.25, "WEIGHT_KEYWORD": 0.25, "WEIGHT_EXPERIENCE": 0.25, "WEIGHT_SECTION_QUALITY": 0.25,
        })

    assert services.resume_parser._timeout == 7
    assert services.resume_parser._max_text_chars == 1234


# ─── concurrency ──────────────────────────────────────────────────────────────

def _blocked_parser(max_concurrent_parses, timeout=0.2):
    import threading

    from app.core.exceptions import ResumeParserBusy  # noqa: F401  (imported to fail early)

    release = threading.Event()
    started = threading.Semaphore(0)

    def blocked(self, path):
        started.release()
        release.wait(10)
        return ParseResult(raw_text="done", parse_error=None)

    parser = ResumeParserService(parse_timeout_seconds=timeout, max_concurrent_parses=max_concurrent_parses)
    return parser, blocked, release, started


def test_a_parse_over_the_concurrency_limit_is_refused_as_busy():
    import threading

    from app.core.exceptions import ResumeParserBusy

    parser, blocked, release, started = _blocked_parser(1, timeout=5)
    with patch.object(ResumeParserService, "parse", blocked):
        first = threading.Thread(target=parser.parse_bytes, args=(b"%PDF-1.4", "a.pdf"), daemon=True)
        first.start()
        assert started.acquire(timeout=5)
        try:
            parser.parse_bytes(b"%PDF-1.4", "b.pdf")
        except ResumeParserBusy as exc:
            assert exc.status_code == 503
            assert exc.retry_after > 0
        else:
            raise AssertionError("expected ResumeParserBusy")
        finally:
            release.set()
            first.join(5)


def test_a_slot_stays_taken_after_the_request_times_out_until_the_worker_finishes():
    from app.core.exceptions import ResumeParserBusy

    parser, blocked, release, started = _blocked_parser(1, timeout=0.2)
    with patch.object(ResumeParserService, "parse", blocked):
        timed_out = parser.parse_bytes(b"%PDF-1.4", "a.pdf")
        assert "timed out" in timed_out.parse_error
        assert started.acquire(timeout=5)
        try:
            parser.parse_bytes(b"%PDF-1.4", "b.pdf")
        except ResumeParserBusy:
            pass
        else:
            raise AssertionError("slot was released on request timeout")
        finally:
            release.set()


def test_the_slot_is_free_again_once_the_worker_finishes():
    import time as _time

    parser, blocked, release, started = _blocked_parser(1, timeout=0.2)
    with patch.object(ResumeParserService, "parse", blocked):
        parser.parse_bytes(b"%PDF-1.4", "a.pdf")
        release.set()
        deadline = _time.monotonic() + 5
        result = None
        while _time.monotonic() < deadline:
            try:
                result = parser.parse_bytes(b"%PDF-1.4", "b.pdf")
                break
            except Exception:
                _time.sleep(0.05)
        assert result is not None and result.raw_text == "done"


def test_a_failing_parse_frees_its_slot():
    parser = ResumeParserService(parse_timeout_seconds=5, max_concurrent_parses=1)

    def boom(self, path):
        raise RuntimeError("bad pdf")

    with patch.object(ResumeParserService, "parse", boom):
        for _ in range(3):
            try:
                parser.parse_bytes(b"%PDF-1.4", "a.pdf")
            except RuntimeError:
                pass


def test_the_factory_passes_the_configured_concurrency_to_the_parser():
    from unittest.mock import MagicMock

    from app.services.service_factory import ServiceFactory

    with patch("app.services.embedding_service.EmbeddingService.get_instance", return_value=MagicMock()):
        services = ServiceFactory.create_all({
            "PARSE_CONCURRENCY": 5,
            "WEIGHT_SEMANTIC": 0.25, "WEIGHT_KEYWORD": 0.25, "WEIGHT_EXPERIENCE": 0.25, "WEIGHT_SECTION_QUALITY": 0.25,
        })

    assert services.resume_parser._max_concurrent_parses == 5


def test_the_concurrency_setting_defaults_to_two(app):
    assert app.config["PARSE_CONCURRENCY"] == 2
