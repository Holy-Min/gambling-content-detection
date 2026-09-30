"""페이지 1개 처리 파이프라인과 도메인 순회, 동시 실행."""
from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from PIL import Image
from playwright.async_api import BrowserContext, Page, TimeoutError as PWTimeout, async_playwright

from .banners import BANNER_JS, filter_candidates, from_js, href_domain
from .blocked import is_blocked_kr, is_challenge_page
from .browser import USER_AGENT, attach_page_guards, new_context, open_browser
from .config import Settings
from .domains import normalize_url, registrable_domain
from .seeds import Seed, append_candidates
from .store import Store, ahash, now_kst, ts_label

# 결제 직전 화면(충전·입금·가입)을 먼저, 그다음 콘텐츠 페이지 순으로 내부 링크를 고른다
PAY_KEYWORDS = ("충전", "입금", "deposit", "recharge", "charge", "cash", "payment", "money")
JOIN_KEYWORDS = ("회원가입", "가입", "join", "register", "signup", "sign-up")
LINK_KEYWORDS = ("event", "notice", "casino", "sports", "slot", "이벤트", "공지", "카지노", "스포츠", "슬롯")
PAGE_KINDS = ("home", "deposit", "register", "login", "other")
STATUSES = ("ok", "blocked_kr", "challenge", "error", "duplicate", "robots_disallow")
RESET_MARKERS = ("ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED", "ERR_SSL_PROTOCOL_ERROR")


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
    pay = [h for h in internal if any(k in h.lower() for k in PAY_KEYWORDS)]
    join = [h for h in internal if h not in pay and any(k in h.lower() for k in JOIN_KEYWORDS)]
    content = [h for h in internal if h not in pay and h not in join and any(k in h.lower() for k in LINK_KEYWORDS)]
    rest = [h for h in internal if h not in pay and h not in join and h not in content]
    return (pay + join + content + rest)[:n]


def page_kind(url: str, title: str, body_text: str, idx: int) -> str:
    """라벨링에 쓸 페이지 종류. 결제 직전 화면(deposit)·가입(register)·로그인 벽(login)을 구분한다."""
    u = (url or "").lower(); t = (title or "").lower(); b = (body_text or "")[:3000].lower()
    if any(k in u or k in t for k in PAY_KEYWORDS):
        return "deposit"
    if any(k in u or k in t for k in JOIN_KEYWORDS):
        return "register"
    if idx == 0:
        return "home"   # 홈 하단 탭에 '충전·입금' 글자가 있어도 홈은 홈이다(본문 규칙은 내부 페이지에만)
    if "충전" in b and ("입금" in b or "계좌" in b or "상품권" in b):
        return "deposit"
    if "로그인" in b and "비밀번호" in b and len(b) < 600:
        return "login"
    return "other"


# 홈에서 보이는 짧은 글자의 클릭 요소를 모두 표시(data-crawler-menu=키)하고 돌려준다. 키워드 판별은 파이썬에서 한다.
MENU_JS = r"""() => {
  const out = [];
  let key = 0;
  for (const el of document.querySelectorAll('a, button, [role=button], [onclick], input[type=button], input[type=submit], li, span, div, p')) {
    let text = (el.tagName === 'INPUT' ? el.value : el.innerText) || el.getAttribute('title') || el.getAttribute('aria-label') || '';
    text = String(text).trim().replace(/\s+/g, ' ');
    if (!text || text.length > 12) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.pointerEvents === 'none') continue;
    el.setAttribute('data-crawler-menu', String(key));
    out.push({key, text, tag: el.tagName.toLowerCase(), href: el.tagName === 'A' ? (el.href || '') : ''});
    key++;
  }
  return out;
}"""
MENU_TEXT_MAX = 12


@dataclass(frozen=True)
class MenuTarget:
    key: int            # data-crawler-menu 값
    text: str
    kind: str           # "deposit" | "register"
    href: str | None    # 내부 URL이면 클릭 대신 그 주소로 이동, None이면 클릭


def _menu_kind(text: str) -> str | None:
    t = text.lower()
    if any(k in t for k in PAY_KEYWORDS):
        return "deposit"
    if any(k in t for k in JOIN_KEYWORDS):
        return "register"
    return None


def menu_targets(items: list[dict], page_domain: str) -> list[MenuTarget]:
    """MENU_JS 결과에서 충전·입금·가입 메뉴를 고른다. 결제 메뉴 먼저, 같은 글자는 한 번(내부 href가 있는 a 우선), 외부 링크·긴 글은 제외."""
    by_text: dict[str, MenuTarget] = {}
    for it in items:
        text = " ".join(str(it.get("text", "")).split())
        if not text or len(text) > MENU_TEXT_MAX:
            continue
        kind = _menu_kind(text)
        if kind is None:
            continue
        raw = str(it.get("href") or "")
        href: str | None
        if raw.startswith(("http://", "https://")):
            if registrable_domain(raw) != page_domain:
                continue   # 사이트 밖으로 나가는 메뉴는 따라가지 않는다
            p = urlsplit(raw)
            href = None if (p.path in ("", "/") and not p.query) else _strip_fragment(raw)   # '#'뿐인 링크는 JS 메뉴
        elif raw == "" or raw.startswith(("javascript:", "#")):
            href = None
        else:
            continue   # mailto:, tel: 등
        t = MenuTarget(key=int(it["key"]), text=text, kind=kind, href=href)
        prev = by_text.get(text)
        if prev is None or (prev.href is None and t.href is not None):
            by_text[text] = t
    return sorted(by_text.values(), key=lambda t: 0 if t.kind == "deposit" else 1)


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
            "title": None, "page_kind": None, "via": None, "full_path": None, "page_height": None, "image_size": None, "phash": None, "banners": [], "error": None}


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
                       store: Store, idx: int, navigate: bool = True, full_page: bool = True,
                       via: str | None = None, kind_hint: str | None = None) -> tuple[dict, list[str], list[str]]:
    """페이지 1개를 처리해 (meta, 내부 링크, 배너의 외부 href) 를 돌려준다. 예외는 meta.status=error로 삼킨다.
    navigate=False면 이미 열린 화면(메뉴 클릭 결과)을 그대로 캡처하고, full_page=False면 뷰포트만 찍는다(모달)."""
    domain = registrable_domain(url)
    meta = _empty_meta(label=label, seed_source=seed_source, url=url, domain=domain, store=store, idx=idx, settings=settings)
    meta["via"] = via
    stem = meta["id"].split("_", 1)[1]
    ddir = store.domain_dir(label, domain)
    links: list[str] = []
    ext_hrefs: list[str] = []
    try:
        for attempt in range(2 if navigate else 0):
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
        if is_challenge_page(await page.title(), body_text):
            await page.wait_for_timeout(5000)  # Cloudflare 확인이 자동으로 풀리는 경우를 한 번 기다린다
            body_text = await page.evaluate("document.body ? document.body.innerText.slice(0, 20000) : ''")
            if is_challenge_page(await page.title(), body_text):
                meta["status"] = "challenge"
                meta["title"] = await page.title()
                meta["error"] = "bot challenge or geo-block page; no content captured"
                return meta, links, ext_hrefs
        try:
            await page.wait_for_load_state("networkidle", timeout=settings.idle_timeout_ms)
        except PWTimeout:
            pass
        meta["page_height"] = await _scroll_through(page, settings)
        meta["title"] = await page.title()
        meta["page_kind"] = page_kind(page.url, meta["title"], body_text, idx)
        if meta["page_kind"] == "other" and kind_hint:
            meta["page_kind"] = kind_hint   # 클릭한 메뉴 글자(충전·가입)로 보정
        ddir.mkdir(parents=True, exist_ok=True)
        full = ddir / f"{stem}_full.png"
        await page.screenshot(path=str(full), full_page=full_page)
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
        msg = str(e)
        if any(m in msg for m in RESET_MARKERS):
            # 국내 ISP는 HTTPS 불법 사이트를 warning.or.kr 대신 연결 리셋으로 막기도 한다
            meta["status"] = "blocked_kr"
            meta["error"] = "connection reset (ISP 차단 추정): " + msg.splitlines()[0][:200]
        else:
            meta["status"] = "error"
            meta["error"] = f"{type(e).__name__}: {msg[:300]}"
    return meta, links, ext_hrefs


_BODY_TEXT_JS = "document.body ? document.body.innerText.slice(0, 20000) : ''"


async def _click_menu(page: Page, target: MenuTarget, *, domain: str, settings: Settings) -> str:
    """메뉴를 클릭하고 결과를 돌려준다: navigated(주소 바뀜) · changed(모달·SPA 등 화면만 바뀜) · external(사이트 밖) · noop."""
    before_url = page.url
    before_text = await page.evaluate(_BODY_TEXT_JS)
    # window.open 팝업은 새 창을 열지 않고 주소만 받아 같은 탭에서 연다(컨텍스트가 팝업을 곧바로 닫기 때문)
    await page.evaluate("() => { window.open = (u) => { window.__crawlerPopup = u ? String(u) : ''; return null; }; }")
    try:
        await page.click(f'[data-crawler-menu="{target.key}"]', timeout=settings.idle_timeout_ms)
    except Exception:
        return "noop"
    await page.wait_for_timeout(settings.settle_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=settings.idle_timeout_ms)
    except PWTimeout:
        pass
    try:
        popup = str(await page.evaluate("window.__crawlerPopup || ''"))
    except Exception:
        popup = ""
    if popup:
        popup = urljoin(before_url, popup)
        if registrable_domain(popup) != domain:
            return "external"
        await page.goto(popup, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
        return "navigated"
    if registrable_domain(page.url) != domain:
        return "external"
    if normalize_url(page.url) != normalize_url(before_url):
        return "navigated"
    after_text = await page.evaluate(_BODY_TEXT_JS)
    return "changed" if after_text != before_text else "noop"


async def _menu_phase(page: Page, *, home_url: str, domain: str, label: str, seed_source: str, settings: Settings,
                      store: Store, idx: int, queue: list[str]) -> tuple[list[dict], int, list[str]]:
    """홈의 충전·입금·가입 메뉴를 처리한다. 내부 URL 메뉴는 큐 맨 앞에 넣고, 버튼·JS 메뉴는 클릭해 바뀐 화면을 캡처한다.
    (캡처 meta 목록, 클릭 횟수, 배너 외부 href) 를 돌려준다. 페이지는 홈이 열린 상태여야 한다."""
    targets = menu_targets(await page.evaluate(MENU_JS), domain)
    known = {normalize_url(u) for u in queue} | {normalize_url(home_url)}
    front: list[str] = []
    for t in targets:
        if t.href and normalize_url(t.href) not in known:
            front.append(t.href)
            known.add(normalize_url(t.href))
    queue[0:0] = front
    metas: list[dict] = []
    ext_hrefs: list[str] = []
    clicks = 0
    for t in [t for t in targets if t.href is None][:settings.max_menu_clicks]:
        if store.ok_count(label, domain) >= settings.per_domain:
            break
        if clicks > 0:   # 이전 클릭이 바꾼 화면을 홈으로 되돌리고, 다시 만들어진 DOM에서 같은 글자의 메뉴를 다시 찾는다
            try:
                await page.goto(home_url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                fresh = {x.text: x for x in menu_targets(await page.evaluate(MENU_JS), domain)}
            except Exception:
                break
            t = fresh.get(t.text)
            if t is None or t.href is not None:
                continue
        clicks += 1
        try:
            result = await _click_menu(page, t, domain=domain, settings=settings)
        except Exception:
            continue
        if result not in ("navigated", "changed"):
            continue
        meta, _links, ext = await capture_page(page, page.url, label=label, seed_source=seed_source, settings=settings, store=store,
                                               idx=idx + len(metas), navigate=False, full_page=(result == "navigated"),
                                               via=f"menu:{t.text}", kind_hint=t.kind)
        store.record(meta)
        metas.append(meta)
        ext_hrefs.extend(ext)
    return metas, clicks, ext_hrefs


async def capture_domain(context: BrowserContext, seed: Seed, *, label: str, settings: Settings,
                         store: Store) -> tuple[list[dict], list[tuple[str, str]], dict[str, int]]:
    """시드 도메인의 홈과 내부 링크를 순서대로 캡처. (metas, [(외부 href, 페이지 도메인)], 메뉴 클릭 집계) 를 돌려준다."""
    domain = registrable_domain(seed.url)
    metas: list[dict] = []
    candidates: list[tuple[str, str]] = []
    stats = {"menu_clicks": 0, "menu_captures": 0}
    queue = [seed.url]
    idx = 0
    delay = settings.delays.get(label, 3.0)
    page = await context.new_page()
    attach_page_guards(page)
    try:
        while queue and store.ok_count(label, domain) < settings.per_domain and idx < settings.per_domain + 2:
            url = queue.pop(0)
            if store.seen_recently(url) and not (settings.refresh and idx == 0):
                continue  # --refresh: 홈은 다시 열어 내부 링크(충전·가입 페이지)를 새로 모은다
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
                if settings.click_menus and meta["status"] in ("ok", "duplicate"):   # --refresh면 홈은 duplicate로 끝난다
                    mm, clicks, mext = await _menu_phase(page, home_url=url, domain=domain, label=label, seed_source=seed.source,
                                                         settings=settings, store=store, idx=idx + 1, queue=queue)
                    metas.extend(mm)
                    candidates.extend((h, domain) for h in mext)
                    stats["menu_clicks"] += clicks
                    stats["menu_captures"] += sum(1 for m in mm if m["status"] == "ok")
                    idx += len(mm)
            idx += 1
            elapsed = time.monotonic() - started
            if queue and delay > elapsed:
                await asyncio.sleep(delay - elapsed)
    finally:
        await page.close()
    return metas, candidates, stats


async def run_capture(settings: Settings, seeds: list[Seed], *, label: str, emit_candidates: bool = False,
                      candidates_path: Path | None = None, known_domains: frozenset[str] = frozenset()) -> dict:
    store = Store(settings.out_root, settings.salt)
    summary: dict = {s: 0 for s in STATUSES}
    summary.update({"skipped_domains": 0, "domains": 0, "candidates_added": 0, "menu_clicks": 0, "menu_captures": 0})
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
                        metas, cands, stats = await capture_domain(context, seed, label=label, settings=settings, store=store)
                    finally:
                        await context.close()
                    for m in metas:
                        summary[m["status"]] += 1
                    for k, v in stats.items():
                        summary[k] += v
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
