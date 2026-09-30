"""페이지 1개 처리 파이프라인과 도메인 순회, 동시 실행."""
from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PIL import Image
from playwright.async_api import BrowserContext, Page, TimeoutError as PWTimeout, async_playwright

from .banners import BANNER_JS, filter_candidates, from_js, href_domain
from .blocked import is_blocked_kr
from .browser import USER_AGENT, attach_page_guards, new_context, open_browser
from .config import Settings
from .domains import normalize_url, registrable_domain
from .seeds import Seed, append_candidates
from .store import Store, ahash, now_kst, ts_label

LINK_KEYWORDS = ("event", "notice", "casino", "sports", "slot", "이벤트", "공지", "카지노", "스포츠", "슬롯")
STATUSES = ("ok", "blocked_kr", "error", "duplicate", "robots_disallow")


def _strip_fragment(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


def pick_internal_links(hrefs: list[str], page_domain: str, current_url: str, n: int) -> list[str]:
    seen = {normalize_url(current_url)}
    internal: list[str] = []
    for h in hrefs:
        if not h.startswith(("http://", "https://")):
            continue
        if registrable_domain(h) != page_domain:
            continue
        key = normalize_url(h)
        if key in seen:
            continue
        seen.add(key)
        internal.append(_strip_fragment(h))
    prioritized = [h for h in internal if any(k in h.lower() for k in LINK_KEYWORDS)]
    rest = [h for h in internal if h not in prioritized]
    return (prioritized + rest)[:n]


@lru_cache(maxsize=1024)
def _robots(host_url: str) -> urllib.robotparser.RobotFileParser | None:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(host_url.rstrip("/") + "/robots.txt")
    try:
        rp.read()
    except Exception:
        return None
    return rp


def robots_allows(url: str, user_agent: str = USER_AGENT) -> bool:
    p = urlsplit(url)
    rp = _robots(f"{p.scheme}://{p.netloc}")
    if rp is None:
        return True
    return rp.can_fetch(user_agent, url)


def _empty_meta(*, label: str, seed_source: str, url: str, domain: str, store: Store, idx: int, settings: Settings) -> dict:
    at = now_kst()
    dhash = store.hash_of(domain)
    return {"id": f"{dhash}_{ts_label(at)}_{idx}", "label": label, "seed_source": seed_source, "url": url,
            "url_norm": normalize_url(url), "final_url": None, "domain": domain, "domain_hash": dhash,
            "captured_at": at.isoformat(), "status": "error",
            "viewport": {"width": settings.viewport_width, "height": settings.viewport_height, "dpr": settings.dpr},
            "title": None, "full_path": None, "page_height": None, "image_size": None, "phash": None, "banners": [], "error": None}


async def _scroll_through(page: Page, settings: Settings) -> int:
    height = int(await page.evaluate("document.documentElement.scrollHeight"))
    step = settings.viewport_height
    for y in range(0, min(height, settings.max_page_height), step):
        await page.evaluate(f"window.scrollTo(0, {y})")
        await page.wait_for_timeout(150)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(settings.settle_ms)
    return int(await page.evaluate("document.documentElement.scrollHeight"))


def _crop_banners(full_png: Path, cands, dpr: int, ddir: Path, stem: str, page_domain: str, root: Path) -> list[dict]:
    out: list[dict] = []
    with Image.open(full_png) as im:
        W, H = im.size
        for k, c in enumerate(cands):
            box = (max(0, int(c.x * dpr)), max(0, int(c.y * dpr)),
                   min(W, int((c.x + c.w) * dpr)), min(H, int((c.y + c.h) * dpr)))
            if box[2] - box[0] < 10 or box[3] - box[1] < 10:
                continue
            path = ddir / f"{stem}_b{k}.png"
            im.crop(box).save(path)
            hd = href_domain(c)
            out.append({"path": str(path.relative_to(root)), "bbox": [round(c.x), round(c.y), round(c.w), round(c.h)],
                        "tag": c.tag, "src": c.src, "href": c.href, "href_domain": hd,
                        "external": bool(hd and hd != page_domain)})
    return out


async def capture_page(page: Page, url: str, *, label: str, seed_source: str, settings: Settings,
                       store: Store, idx: int) -> tuple[dict, list[str], list[str]]:
    """페이지 1개를 처리해 (meta, 내부 링크, 배너의 외부 href) 를 돌려준다. 예외는 meta.status=error로 삼킨다."""
    domain = registrable_domain(url)
    meta = _empty_meta(label=label, seed_source=seed_source, url=url, domain=domain, store=store, idx=idx, settings=settings)
    stem = meta["id"].split("_", 1)[1]
    ddir = store.domain_dir(label, domain)
    links: list[str] = []
    ext_hrefs: list[str] = []
    try:
        for attempt in range(2):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                break
            except PWTimeout:
                if attempt == 1:
                    raise
        meta["final_url"] = page.url
        body_text = await page.evaluate("document.body ? document.body.innerText.slice(0, 20000) : ''")
        if is_blocked_kr(page.url, body_text):
            meta["status"] = "blocked_kr"
            return meta, links, ext_hrefs
        try:
            await page.wait_for_load_state("networkidle", timeout=settings.idle_timeout_ms)
        except PWTimeout:
            pass
        meta["page_height"] = await _scroll_through(page, settings)
        meta["title"] = await page.title()
        ddir.mkdir(parents=True, exist_ok=True)
        full = ddir / f"{stem}_full.png"
        await page.screenshot(path=str(full), full_page=True)
        dpr = settings.dpr
        with Image.open(full) as im:
            if im.height > settings.max_page_height * dpr:
                im.crop((0, 0, im.width, settings.max_page_height * dpr)).save(full)
        with Image.open(full) as im:
            meta["image_size"] = [im.width, im.height]
        cands = filter_candidates(from_js(await page.evaluate(BANNER_JS)), domain, label)
        meta["banners"] = _crop_banners(full, cands, dpr, ddir, stem, domain, store.root)
        ext_hrefs = sorted({b["href"] for b in meta["banners"] if b["external"]})
        if idx == 0:
            hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            links = pick_internal_links(hrefs, domain, page.url, settings.per_domain - 1)
        meta["phash"] = ahash(full)
        dup = store.find_duplicate(label, domain, meta["phash"])
        if dup:
            meta["status"] = "duplicate"
            meta["error"] = f"near-duplicate of {dup}"
            for b in meta["banners"]:
                (store.root / b["path"]).unlink(missing_ok=True)
            full.unlink(missing_ok=True)
            meta["banners"] = []
            return meta, links, ext_hrefs
        meta["full_path"] = str(full.relative_to(store.root))
        meta["status"] = "ok"
    except Exception as e:  # 페이지 단위 격리: 어떤 예외도 다음 페이지로 넘어간다
        meta["status"] = "error"
        meta["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return meta, links, ext_hrefs


async def capture_domain(context: BrowserContext, seed: Seed, *, label: str, settings: Settings,
                         store: Store) -> tuple[list[dict], list[tuple[str, str]]]:
    """시드 도메인의 홈과 내부 링크를 순서대로 캡처. (metas, [(외부 href, 페이지 도메인)]) 를 돌려준다."""
    domain = registrable_domain(seed.url)
    metas: list[dict] = []
    candidates: list[tuple[str, str]] = []
    queue = [seed.url]
    idx = 0
    delay = settings.delays.get(label, 3.0)
    page = await context.new_page()
    attach_page_guards(page)
    try:
        while queue and store.ok_count(label, domain) < settings.per_domain and idx < settings.per_domain + 2:
            url = queue.pop(0)
            if store.seen_recently(url):
                continue
            if label in settings.robots_labels and not robots_allows(url):
                meta = _empty_meta(label=label, seed_source=seed.source, url=url, domain=domain, store=store, idx=idx, settings=settings)
                meta["status"] = "robots_disallow"
                store.record(meta); metas.append(meta); idx += 1
                continue
            started = time.monotonic()
            meta, links, ext = await capture_page(page, url, label=label, seed_source=seed.source,
                                                  settings=settings, store=store, idx=idx)
            store.record(meta); metas.append(meta)
            candidates.extend((h, domain) for h in ext)
            if idx == 0 and meta["status"] == "error" and "ERR_NAME_NOT_RESOLVED" in (meta["error"] or ""):
                break  # DNS 실패 도메인은 내부 링크를 시도하지 않는다
            if idx == 0:
                queue.extend(links)
            idx += 1
            elapsed = time.monotonic() - started
            if queue and delay > elapsed:
                await asyncio.sleep(delay - elapsed)
    finally:
        await page.close()
    return metas, candidates


async def run_capture(settings: Settings, seeds: list[Seed], *, label: str, emit_candidates: bool = False,
                      candidates_path: Path | None = None, known_domains: frozenset[str] = frozenset()) -> dict:
    store = Store(settings.out_root, settings.salt)
    summary: dict = {s: 0 for s in STATUSES}
    summary.update({"skipped_domains": 0, "domains": 0, "candidates_added": 0})
    todo: list[Seed] = []
    for seed in seeds:
        if store.ok_count(label, registrable_domain(seed.url)) >= settings.per_domain:
            summary["skipped_domains"] += 1
            continue
        todo.append(seed)
        if len(todo) >= settings.max_domains:
            break
    sem = asyncio.Semaphore(settings.concurrency)
    all_candidates: list[tuple[str, str]] = []
    async with async_playwright() as pw:
        browser = await open_browser(pw)
        try:
            async def work(seed: Seed) -> None:
                async with sem:
                    context = await new_context(pw, browser, settings)
                    try:
                        metas, cands = await capture_domain(context, seed, label=label, settings=settings, store=store)
                    finally:
                        await context.close()
                    for m in metas:
                        summary[m["status"]] += 1
                    all_candidates.extend(cands)
                    summary["domains"] += 1
            await asyncio.gather(*(work(s) for s in todo))
        finally:
            await browser.close()
    if emit_candidates and candidates_path is not None and all_candidates:
        by_page: dict[str, list[str]] = defaultdict(list)
        for href, page_domain in all_candidates:
            by_page[page_domain].append(href)
        known = set(known_domains)
        for page_domain, hrefs in by_page.items():
            added = append_candidates(candidates_path, hrefs, source=f"banner:{page_domain}", known_domains=known)
            known.update(registrable_domain(u) for u in added)
            summary["candidates_added"] += len(added)
    return summary
