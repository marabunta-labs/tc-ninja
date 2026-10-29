import pytest

import fetchers
import scraping

ES = ("El servicio recoge los datos de usuario para que la aplicación funcione y se mejore. " * 40)
EN = ("The service collects the information that you provide to us and uses it for the purposes of the terms. " * 30)


@pytest.fixture
def chain(monkeypatch):
    def install(**fns):
        monkeypatch.setattr(fetchers, "FETCHERS", fns)
    return install


def test_detect_language():
    assert scraping.detect_language(ES) == "es"
    assert scraping.detect_language(EN) == "en"
    assert scraping.detect_language("short text") is None
    assert scraping.detect_language("zxq " * 200) is None


def test_first_valid_right_language_wins(chain):
    calls = []
    chain(a=lambda u, l: calls.append("a") or ES, b=lambda u, l: calls.append("b") or ES)
    r = fetchers.fetch_source_text("https://r.jina.ai/https://x.com/t", "es", ["a", "b"])
    assert (r.fetcher, r.language_ok, r.detected_language) == ("a", True, "es")
    assert calls == ["a"]


def test_fallback_on_invalid_and_error(chain):
    def boom(u, l):
        raise scraping.FetchError("HTTP 403")
    chain(a=boom, b=lambda u, l: "tiny", c=lambda u, l: ES)
    assert fetchers.fetch_source_text("https://x.com", "es", ["a", "b", "c"]).fetcher == "c"


def test_language_preference_over_earlier_wrong_language(chain):
    chain(a=lambda u, l: EN, b=lambda u, l: ES)
    r = fetchers.fetch_source_text("https://x.com", "es", ["a", "b"])
    assert r.fetcher == "b" and r.language_ok


def test_wrong_language_only_returns_best_with_flag(chain):
    chain(a=lambda u, l: EN, b=lambda u, l: EN + EN)
    r = fetchers.fetch_source_text("https://x.com", "es", ["a", "b"])
    assert r.fetcher == "b" and not r.language_ok and r.detected_language == "en"


def test_all_fail_lists_each_failure(chain):
    def boom(u, l):
        raise scraping.FetchError("HTTP 500")
    chain(a=boom, b=lambda u, l: "tiny")
    with pytest.raises(scraping.FetchError) as e:
        fetchers.fetch_source_text("https://x.com", "es", ["a", "b"])
    assert "a: " in str(e.value) and "b: " in str(e.value)


def test_missing_dependency_is_skipped(chain):
    def missing(u, l):
        raise fetchers.FetcherUnavailable("playwright not installed")
    chain(a=missing, b=lambda u, l: ES)
    assert fetchers.fetch_source_text("https://x.com", "es", ["a", "b"]).fetcher == "b"
    with pytest.raises(scraping.FetchError, match="skipped"):
        fetchers.fetch_source_text("https://x.com", "es", ["a"])


def test_chain_for_override():
    cfg = {"sourceFetchers": {"https://x.com/p": ["playwright", "jina"]}}
    assert fetchers.chain_for(cfg, "https://r.jina.ai/https://x.com/p") == ["playwright", "jina"]
    assert fetchers.chain_for(cfg, "https://r.jina.ai/https://x.com/other") is None
    assert fetchers.chain_for({}, "https://x.com/p") is None
