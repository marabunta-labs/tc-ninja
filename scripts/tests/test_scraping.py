import pytest
import requests

import scraping
from scraping import (
    FetchError,
    InvalidContent,
    check_shrink,
    clean_text,
    content_hash,
    fetch_source,
    next_version_tag,
    real_url,
    strip_jina_header,
    validate_content,
)

JINA_PAGE = (
    "Title: Terms\n\nURL Source: https://example.com/tos\n\n"
    "Published Time: 2026-01-01T10:00:00Z\n\nMarkdown Content:\n"
)


class FakeResponse:
    def __init__(self, status=200, text="ok", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class FakeHttp:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def get(self, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestCleaning:
    def test_strips_jina_header(self):
        assert strip_jina_header(JINA_PAGE + "Body").strip() == "Body"

    def test_header_timestamp_does_not_change_hash(self):
        a = clean_text(JINA_PAGE + "Same body")
        b = clean_text(JINA_PAGE.replace("10:00:00", "23:59:59") + "Same body")
        assert content_hash(a) == content_hash(b)

    def test_removes_images_and_link_targets(self):
        raw = "See [our policy](https://x.com/p?tracking=abc123) ![logo](https://cdn/x.png?oh=9)here"
        assert clean_text(raw) == "See our policy here"

    def test_keeps_parentheses_in_url(self):
        assert clean_text("[a](https://en.wikipedia.org/wiki/X_(y)) b") == "a b"

    def test_real_changes_change_hash(self):
        assert content_hash(clean_text("We keep data 30 days")) != content_hash(clean_text("We keep data 90 days"))

    def test_drops_cookie_banner_buttons(self):
        raw = "Policy text here.\n  Accept All \nManage Data Settings\nMore policy text."
        assert clean_text(raw) == "Policy text here.\n\n\nMore policy text.".replace("\n\n\n", "\n\n")

    def test_collapses_whitespace(self):
        assert clean_text("a   b\r\n\r\n\r\n\r\n c ") == "a b\n\nc"


class TestValidation:
    def test_too_short_rejected(self):
        with pytest.raises(InvalidContent):
            validate_content("tiny", "src")

    def test_login_wall_rejected(self):
        with pytest.raises(InvalidContent, match="block page"):
            validate_content("Please enable JavaScript to continue. " * 60, "src")

    def test_long_document_mentioning_captcha_is_fine(self):
        validate_content("We may use a CAPTCHA. " + "Legal text. " * 1_000, "src")

    def test_shrink_guard(self):
        with pytest.raises(InvalidContent):
            check_shrink(10_000, 3_000)
        check_shrink(10_000, 6_000)
        check_shrink(None, 10)


class TestFetch:
    def test_retries_then_succeeds(self):
        http = FakeHttp(FakeResponse(429), requests.Timeout("slow"), FakeResponse(200, "done"))
        assert fetch_source("https://r.jina.ai/https://a.com", http, sleep=lambda s: None) == "done"
        assert http.calls == 3

    def test_gives_up_after_max_attempts(self):
        http = FakeHttp(*[FakeResponse(503)] * scraping.MAX_ATTEMPTS)
        with pytest.raises(FetchError, match="HTTP 503"):
            fetch_source("https://r.jina.ai/https://a.com", http, sleep=lambda s: None)
        assert http.calls == scraping.MAX_ATTEMPTS

    def test_does_not_retry_client_errors(self):
        http = FakeHttp(FakeResponse(404))
        with pytest.raises(FetchError):
            fetch_source("https://r.jina.ai/https://a.com", http, sleep=lambda s: None)
        assert http.calls == 1

    def test_honours_retry_after(self):
        waits = []
        http = FakeHttp(FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, "ok"))
        fetch_source("https://a.com", http, sleep=waits.append)
        assert waits == [7]


class TestVersioning:
    def test_first_version_of_the_day(self):
        assert next_version_tag("2026-09-30", set()) == "2026-09-30"

    def test_second_change_same_day(self):
        assert next_version_tag("2026-09-30", {"2026-09-30"}) == "2026-09-30.2"
        assert next_version_tag("2026-09-30", {"2026-09-30", "2026-09-30.2"}) == "2026-09-30.3"

    def test_real_url(self):
        assert real_url("https://r.jina.ai/https://x.com/en/tos") == "https://x.com/en/tos"
        assert real_url("https://x.com/en/tos") == "https://x.com/en/tos"
