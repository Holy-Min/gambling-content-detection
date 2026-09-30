"""시드 확장: 검증 커뮤니티 페이지의 외부 링크, Yahoo 검색 결과."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from playwright.async_api import async_playwright

from .browser import attach_page_guards, new_context, open_browser
from .config import Settings
from .domains import registrable_domain
from .seeds import append_candidates, is_platform, read_seeds

# DuckDuckGo HTML 엔드포인트는 헤드리스 브라우저에 403을 돌려주어(2026-09 확인) Yahoo 검색을 쓴다.
SEARCH_URL = "https://search.yahoo.com/search?p={q}"
SEARCH_RESULT_SELECTOR = "div.algo h3 a, div.compTitle h3 a"
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


async def discover_community(settings: Settings, community_csv: Path, out_csv: Path, known_domains: set[str]) -> int:
    seeds = read_seeds(community_csv)
    added_total = 0
    async with async_playwright() as pw:
        browser = await open_browser(pw)
        context = await new_context(pw, browser, settings)
        page = await context.new_page(); attach_page_guards(page)
        try:
            for seed in seeds:
                page_domain = registrable_domain(seed.url)
                try:
                    hrefs = await _collect_hrefs(page, seed.url, settings)
                except Exception as e:
                    print(f"[community] {seed.url}: {type(e).__name__}")
                    continue
                urls = external_domains_urls(hrefs, page_domain)
                added = append_candidates(out_csv, urls, source=f"community:{page_domain}", known_domains=known_domains)
                known_domains.update(registrable_domain(u) for u in added)
                added_total += len(added)
                print(f"[community] {page_domain}: 외부 도메인 {len(urls)}개 중 {len(added)}개 추가")
                await asyncio.sleep(settings.delays.get("gambling", 3.0))
        finally:
            await context.close(); await browser.close()
    return added_total


async def discover_search(settings: Settings, keywords_path: Path, out_csv: Path, known_domains: set[str],
                          per_keyword: int = 20) -> int:
    keywords = [k.strip() for k in Path(keywords_path).read_text(encoding="utf-8").splitlines()
                if k.strip() and not k.startswith("#")]
    added_total = 0
    async with async_playwright() as pw:
        browser = await open_browser(pw)
        context = await new_context(pw, browser, settings)
        page = await context.new_page(); attach_page_guards(page)
        try:
            for kw in keywords:
                try:
                    await page.goto(SEARCH_URL.format(q=quote(kw)), wait_until="load", timeout=settings.page_timeout_ms)
                    await page.wait_for_timeout(2000)
                    hrefs = await page.eval_on_selector_all(SEARCH_RESULT_SELECTOR, "els => els.map(e => e.href)")
                    links = parse_search_links(hrefs)[:per_keyword]
                except Exception as e:
                    print(f"[search] {kw}: {type(e).__name__}")
                    continue
                urls = external_domains_urls(links, "yahoo.com")
                added = append_candidates(out_csv, urls, source=f"search:{kw}", known_domains=known_domains)
                known_domains.update(registrable_domain(u) for u in added)
                added_total += len(added)
                print(f"[search] {kw}: 결과 {len(links)}개 중 {len(added)}개 추가")
                await asyncio.sleep(3.0)
        finally:
            await context.close(); await browser.close()
    return added_total
