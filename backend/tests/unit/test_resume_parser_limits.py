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
