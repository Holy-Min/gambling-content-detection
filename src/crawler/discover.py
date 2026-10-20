"""시드 확장: 검증 커뮤니티 페이지의 외부 링크, Yahoo 검색 결과."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from playwright.async_api import async_playwright

from .blocked import is_blocked_kr
from .browser import attach_page_guards, new_context, open_browser
from .config import Settings
from .domains import registrable_domain
from .seeds import append_candidates, is_platform, read_keywords, read_seeds

# DuckDuckGo HTML 엔드포인트는 헤드리스 브라우저에 403을 돌려주어(2026-09 확인) Yahoo 검색을 쓴다.
SEARCH_URL = "https://search.yahoo.com/search?p={q}"
SEARCH_RESULT_SELECTOR = "#web h3 a, div.algo h3 a, div.compTitle h3 a"
SEARCH_FALLBACK_SELECTOR = "#web a[href], #main a[href]"  # 광고형 레이아웃(카지노 키워드 등)에서 h3가 없을 때
_ENGINE_HOSTS = ("yahoo.com", "yimg.com", "duckduckgo.com")


def resolve_search_href(href: str) -> str | None:
    """Yahoo 결과 링크를 실제 URL로. r.search.yahoo.com/...RU=<encoded>... 형태의 리다이렉트를 푼다."""
    if not href.startswith(("http://", "https://")):
        return None
    parts = urlsplit(href)
    if parts.hostname and parts.hostname.endswith("search.yahoo.com"):
        m = re.search(r"/RU=([^/]+)/", parts.path)
        if m:
            target = unquote(m.group(1))
            return target if target.startswith(("http://", "https://")) else None
        return None
    if any(parts.hostname and parts.hostname.endswith(h) for h in _ENGINE_HOSTS):
        return None
    return href


def parse_search_links(hrefs: list[str]) -> list[str]:
    out: list[str] = []
    for h in hrefs:
        t = resolve_search_href(h)
        if t and t not in out:
            out.append(t)
    return out


def external_domains_urls(hrefs: list[str], page_domain: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for h in hrefs:
        if not h.startswith(("http://", "https://")):
            continue
        dom = registrable_domain(h)
        if not dom or dom == page_domain or is_platform(dom) or dom in seen:
            continue
        seen.add(dom)
        out.append(h)
    return out


async def _collect_hrefs(page, url: str, settings: Settings) -> list[str]:
    await page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=settings.idle_timeout_ms)
    except Exception:
        pass
    return await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")


RESET_MARKERS = ("ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED", "ERR_SSL_PROTOCOL_ERROR")


@dataclass
class CommunityTally:
    """커뮤니티 수집 결과: 추가된 후보 수, 열어 본 페이지 수, 마감 때문에 중단했는지."""
    added: int = 0
    pages: int = 0
    timed_out: bool = False


async def discover_community(settings: Settings, community_csv: Path, out_csv: Path, known_domains: set[str],
                             deadline: float | None = None) -> CommunityTally:
    """커뮤니티 페이지마다 새 컨텍스트를 쓴다(한 페이지의 오류가 다음 페이지로 번지지 않게).
    deadline(time.monotonic 기준)이 지나면 다음 시드를 시작하지 않고 timed_out 으로 멈춘다."""
    seeds = read_seeds(community_csv)
    tally = CommunityTally()
    async with async_playwright() as pw:
        browser = await open_browser(pw)
        try:
            for seed in seeds:
                if deadline is not None and time.monotonic() >= deadline:
                    tally.timed_out = True
                    break
                tally.pages += 1
                page_domain = registrable_domain(seed.url)
                context = await new_context(pw, browser, settings)
                try:
                    page = await context.new_page(); attach_page_guards(page)
                    hrefs = await _collect_hrefs(page, seed.url, settings)
                    body = await page.evaluate("document.body ? document.body.innerText.slice(0, 20000) : ''")
                    if is_blocked_kr(page.url, body):
                        print(f"[community] {page_domain}: 차단 안내 페이지(blocked_kr)")
                        continue
                except Exception as e:
                    msg = str(e)
                    why = "연결 리셋(ISP 차단 추정)" if any(m in msg for m in RESET_MARKERS) else f"{type(e).__name__}: {msg[:80]}"
                    print(f"[community] {page_domain}: {why}")
                    continue
                finally:
                    await context.close()
                urls = external_domains_urls(hrefs, page_domain)
                added = append_candidates(out_csv, urls, source=f"community:{page_domain}", known_domains=known_domains)
                known_domains.update(registrable_domain(u) for u in added)
                tally.added += len(added)
                print(f"[community] {page_domain}: 외부 도메인 {len(urls)}개 중 {len(added)}개 추가")
                await asyncio.sleep(settings.delays.get("gambling", 3.0))
        finally:
            await browser.close()
    return tally


class SearchTally:
    """키워드별 결과·추가 수. 결과 링크 0개가 stop_after 번 연속이면 Yahoo 봇 확인으로 보고 bot_check 를 켠다."""

    def __init__(self, stop_after: int = 2):
        self.stop_after = stop_after
        self.links: dict[str, int] = {}
        self.added: dict[str, int] = {}
        self.zero_streak = 0
        self.bot_check = False
        self.timed_out = False

    def add(self, keyword: str, links: int, added: int) -> None:
        self.links[keyword] = links
        self.added[keyword] = added
        self.zero_streak = self.zero_streak + 1 if links == 0 else 0
        if self.zero_streak >= self.stop_after:
            self.bot_check = True

    @property
    def total_added(self) -> int:
        return sum(self.added.values())


async def discover_search_keywords(settings: Settings, keywords: list[str], out_csv: Path, known_domains: set[str],
                                   per_keyword: int = 20, stop_after_zero: int | None = 2,
                                   deadline: float | None = None) -> SearchTally:
    """키워드마다 새 브라우저 컨텍스트를 쓴다(같은 컨텍스트로 질의를 반복하면 Yahoo가 봇 확인 페이지로 보낸다).
    stop_after_zero 가 있으면 결과 0개가 그만큼 연속일 때 멈춘다(야간 루프). None 이면 끝까지 돈다(수동).
    deadline(time.monotonic 기준)이 지나면 다음 키워드를 시작하지 않고 tally.timed_out 으로 멈춘다."""
    tally = SearchTally(stop_after_zero if stop_after_zero else 10 ** 9)
    async with async_playwright() as pw:
        browser = await open_browser(pw)
        try:
            for kw in keywords:
                if deadline is not None and time.monotonic() >= deadline:
                    tally.timed_out = True
                    break
                context = await new_context(pw, browser, settings)
                links: list[str] = []
                try:
                    page = await context.new_page(); attach_page_guards(page)
                    await page.goto(SEARCH_URL.format(q=quote(kw)), wait_until="load", timeout=settings.page_timeout_ms)
                    await page.wait_for_timeout(2000)
                    hrefs = await page.eval_on_selector_all(SEARCH_RESULT_SELECTOR, "els => els.map(e => e.href)")
                    if not hrefs:
                        hrefs = await page.eval_on_selector_all(SEARCH_FALLBACK_SELECTOR, "els => els.map(e => e.href)")
                    links = parse_search_links(hrefs)[:per_keyword]
                except Exception as e:
                    print(f"[search] {kw}: {type(e).__name__}")
                finally:
                    await context.close()
                urls = external_domains_urls(links, "yahoo.com")
                added = append_candidates(out_csv, urls, source=f"search:{kw}", known_domains=known_domains)
                known_domains.update(registrable_domain(u) for u in added)
                tally.add(kw, len(links), len(added))
                print(f"[search] {kw}: 결과 {len(links)}개 중 {len(added)}개 추가")
                if tally.bot_check:
                    print(f"[search] 결과 0개가 {tally.stop_after}회 연속 — 봇 확인으로 보고 중단")
                    break
                await asyncio.sleep(4.0)
        finally:
            await browser.close()
    return tally


async def discover_search(settings: Settings, keywords_path: Path, out_csv: Path, known_domains: set[str],
                          per_keyword: int = 20) -> int:
    """키워드 파일을 읽어 조기 종료 없이 수확한다(수동 실행용)."""
    tally = await discover_search_keywords(settings, read_keywords(Path(keywords_path)), out_csv, known_domains,
                                           per_keyword, stop_after_zero=None)
    return tally.total_added
