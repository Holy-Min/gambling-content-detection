from crawler.discover import external_domains_urls, parse_search_links, resolve_search_href


def test_resolve_search_href_unwraps_yahoo_redirect_and_drops_engine_links():
    wrapped = "https://r.search.yahoo.com/_ylt=Awr;_ylu=Y29s/RV=2/RE=1/RO=10/RU=https%3a%2f%2fmtpolice.kr%2fhome%2f/RK=2/RS=abc-"
    assert resolve_search_href(wrapped) == "https://mtpolice.kr/home/"
    assert resolve_search_href("https://mtcheck.net/main") == "https://mtcheck.net/main"
    assert resolve_search_href("https://search.yahoo.com/preferences") is None
    assert resolve_search_href("javascript:void(0)") is None


def test_parse_search_links_dedups_in_order():
    hrefs = ["https://mtpolice.kr/home/", "https://mtpolice.kr/home/", "https://jusotour.com/scam_verify", "https://s.yimg.com/x"]
    assert parse_search_links(hrefs) == ["https://mtpolice.kr/home/", "https://jusotour.com/scam_verify"]


def test_external_domains_urls_filters_same_domain_platform_and_dups():
    hrefs = ["https://verify.com/a", "https://www.site-a.com/x", "https://site-a.com/y", "https://naver.com/blog",
             "javascript:void(0)", "https://site-b.net/", "https://t.me/chan"]
    assert external_domains_urls(hrefs, "verify.com") == ["https://www.site-a.com/x", "https://site-b.net/"]


from crawler.discover import SearchTally


def test_search_tally_flags_bot_check_after_consecutive_zero_results():
    t = SearchTally(stop_after=2)
    t.add("a", links=10, added=3); t.add("b", links=0, added=0); t.add("c", links=5, added=0)
    assert not t.bot_check and t.zero_streak == 0 and t.total_added == 3
    t.add("d", links=0, added=0)
    assert not t.bot_check and t.zero_streak == 1
    t.add("e", links=0, added=0)
    assert t.bot_check and t.links == {"a": 10, "b": 0, "c": 5, "d": 0, "e": 0} and t.added["a"] == 3


def test_search_tally_timed_out_defaults_false():
    assert SearchTally().timed_out is False


def test_community_tally_fields():
    from crawler.discover import CommunityTally
    t = CommunityTally(added=3, pages=2, timed_out=True)
    assert (t.added, t.pages, t.timed_out) == (3, 2, True)


import asyncio
import pytest
from crawler import discover
from tests.conftest import fast_settings
from crawler.discover import is_normal_source, search_source
from crawler.seeds import read_keywords


def test_search_source_prefix():
    assert search_source("토토사이트") == "search:토토사이트"
    assert search_source("게임 캐시 충전", "normal") == "search-normal:게임 캐시 충전"
    with pytest.raises(ValueError):
        search_source("x", "etc")


def test_is_normal_source():
    assert is_normal_source("search-normal:a")
    assert not any(is_normal_source(s) for s in ("search:a", "banner:x", "community:y", ""))


class _FakePage:
    async def goto(self, *a, **k): pass
    async def wait_for_timeout(self, *a): pass
    async def eval_on_selector_all(self, *a): return ["https://shop-a.com/x"]
    def on(self, *a, **k): pass
    def route(self, *a, **k): pass


class _FakeContext:
    async def new_page(self): return _FakePage()
    async def close(self): pass


class _FakeBrowser:
    async def close(self): pass


class _FakePW:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def _patch_fakes(monkeypatch, sources):
    async def fake_open(pw): return _FakeBrowser()
    async def fake_ctx(pw, b, s): return _FakeContext()
    async def no_sleep(*a): pass
    def fake_append(out, urls, source, known_domains):
        sources.append(source)
        return list(urls)
    monkeypatch.setattr(discover, "async_playwright", lambda: _FakePW())
    monkeypatch.setattr(discover, "open_browser", fake_open)
    monkeypatch.setattr(discover, "new_context", fake_ctx)
    monkeypatch.setattr(discover, "attach_page_guards", lambda page: None)
    monkeypatch.setattr(discover, "append_candidates", fake_append)
    monkeypatch.setattr(discover.asyncio, "sleep", no_sleep)


@pytest.mark.parametrize("track,expected", [("normal", "search-normal:게임 캐시 충전"), ("gambling", "search:게임 캐시 충전")])
def test_discover_search_keywords_source_by_track(monkeypatch, tmp_path, track, expected):
    sources: list[str] = []
    _patch_fakes(monkeypatch, sources)
    asyncio.run(discover.discover_search_keywords(fast_settings(tmp_path), ["게임 캐시 충전"], tmp_path / "c.csv", set(), track=track))
    assert sources == [expected]


def test_discover_search_keywords_default_track_is_gambling(monkeypatch, tmp_path):
    sources: list[str] = []
    _patch_fakes(monkeypatch, sources)
    asyncio.run(discover.discover_search_keywords(fast_settings(tmp_path), ["a"], tmp_path / "c.csv", set()))
    assert sources == ["search:a"]


def test_keywords_normal_file_has_15():
    from pathlib import Path
    kws = read_keywords(Path(__file__).resolve().parents[1] / "seeds" / "keywords_normal.txt")
    assert len(kws) == 15 and kws[0] == "게임 캐시 충전" and kws[-1] == "경품 응모"
