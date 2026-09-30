# 도박 화면 데이터셋 수집기(crawler) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Playwright로 도박·정상 사이트를 모바일 뷰포트로 렌더링해 전체 화면 스크린샷 + 배너 크롭 + 메타데이터를 라벨별로 저장하는 CLI(`python -m crawler discover|capture|stats`)를 만든다.

**Architecture:** 순수 함수 모듈(`domains`, `seeds`, `blocked`, `banners`, `store`)을 먼저 테스트와 함께 만들고, 그 위에 Playwright(async) 컨텍스트 팩토리(`browser`)와 페이지 처리 파이프라인(`capture`), 시드 확장(`discover`), CLI(`__main__`)를 얹는다. 배너 크롭은 전체 페이지 PNG를 Pillow로 잘라 만들어 요소 핸들 소멸 문제를 피한다. 결과는 저장소 밖 `/Users/seongmin/Downloads/논문 관련/dataset/`에 쓴다.

**Tech Stack:** Python 3.12, playwright(async API, Chromium), tldextract, Pillow, pytest, pytest-asyncio. 저장소 안 `.venv`.

**Spec:** `docs/superpowers/specs/2026-09-23-gambling-crawler-design.md`

## Global Constraints

- Python 3.12 (`/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`), 가상환경은 저장소 루트 `.venv` (이미 `.gitignore`에 있음).
- 의존성: `playwright`, `tldextract`, `Pillow`, `pytest`, `pytest-asyncio`. 그 외 추가 금지(`.env` 파싱도 직접 구현).
- 기본 저장 루트: `/Users/seongmin/Downloads/논문 관련/dataset/`. 우선순위 CLI `--out` > `.env`의 `CRAWLER_OUT` > 기본값. 기존 `도박 사이트 이미지/` 폴더와 PDF는 건드리지 않는다.
- 도메인 해시 = `sha256(salt + 등록도메인)[:12]`, 솔트는 `.env`의 `CRAWLER_SALT`. 솔트가 없으면 실행 거부(`SystemExit`).
- 라벨 4종: `gambling`, `embedded_banner`, `hard_negative`, `normal`. 상태 값: `ok`, `blocked_kr`, `error`, `duplicate`, `robots_disallow`.
- 기기 프로필 `Pixel 7`(412×915, DPR 2), 로케일 `ko-KR`, 타임존 `Asia/Seoul`. `accept_downloads=False`, `ignore_https_errors=True`, `media`·`font` 요청 차단(`image`는 허용).
- 페이지 타임아웃 20초(1회 재시도), 네트워크 유휴 대기 최대 5초, 안정화 1.5초, 전체 스크린샷 높이 상한 15,000px.
- 배너 후보: 표시 중, 너비 ≥150, 높이 ≥40, 면적 ≥12,000, 가로세로비 0.2~8, IoU ≥0.8 중복 제거, 면적 상위 12개. `embedded_banner`는 외부 href만.
- 차단 판정: 최종 URL 호스트 `warning.or.kr`/`www.warning.or.kr` 또는 본문에 "불법·유해정보(사이트)에 대한 차단 안내", 또는 "방송통신심의위원회"와 "차단"이 함께 있음.
- 간격: `gambling`·`embedded_banner` 3초, `hard_negative`·`normal` 5초 + robots.txt 준수. 동시 컨텍스트 3개. 도메인당 최대 5페이지.
- 퍼셉추얼 해시 16×16 average hash, 같은 도메인 `ok` 페이지와 해밍 거리 ≤5면 `duplicate`(파일 삭제).
- 재실행: `index.jsonl`로 도메인별 `ok` 수 확인, 정규화 URL이 7일 내 캡처됐으면 건너뜀.
- 열람만: 스크롤·팝업 닫기 외 클릭·입력·다운로드 없음. 자동 발견은 `seeds/candidates.csv`에만 쓴다.
- 실제 도박 사이트·외부 네트워크를 치는 테스트 금지. 통합 테스트는 로컬 `http.server` 픽스처만 사용.
- 커밋 메시지는 영문 conventional 형식, 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## File Structure

```
pyproject.toml                    패키지·pytest 설정 (src 레이아웃)
requirements.txt                  의존성 5개
.env.example                      CRAWLER_OUT, CRAWLER_SALT
seeds/README.md                   시드 작성법
seeds/{gambling,embedded_banner,hard_negative,normal,community_lists,candidates}.csv  헤더만
seeds/keywords.txt                기본 키워드 10개
seeds/blocklist.txt               절대 열지 않을 도메인 (빈 템플릿)
src/crawler/__init__.py
src/crawler/domains.py            등록 도메인, 해시, URL 정규화
src/crawler/seeds.py              시드 CSV 읽기/후보 추가, 플랫폼 제외
src/crawler/blocked.py            차단 안내 페이지 판정
src/crawler/banners.py            브라우저 추출 JS + 배너 후보 필터
src/crawler/store.py              경로·meta/index 기록·재실행 판단·퍼셉추얼 해시
src/crawler/config.py             Settings, .env 로더
src/crawler/browser.py            Playwright 컨텍스트 팩토리(기기·차단·팝업)
src/crawler/capture.py            페이지 처리 파이프라인, 도메인 순회, 동시 실행
src/crawler/discover.py           커뮤니티 링크·DuckDuckGo 검색 수집
src/crawler/stats.py              index 집계
src/crawler/__main__.py           argparse CLI
tests/test_domains.py … test_stats.py   단위 테스트
tests/test_capture_integration.py       로컬 픽스처 통합 테스트
tests/fixtures/site/{index,page2,page3,warning}.html
```

---

### Task 1: 프로젝트 골격과 환경

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.env.example`, `src/crawler/__init__.py`, `tests/__init__.py`
- Modify: `.gitignore` (`.env` 이미 있음 → `seeds/candidates.csv`는 추적함, 변경 없음)

**Interfaces:**
- Produces: 패키지 `crawler` import 가능, `pytest` 실행 가능, `.venv/bin/playwright` + Chromium 설치.

- [ ] **Step 1: pyproject.toml 작성**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "gambling-crawler"
version = "0.1.0"
description = "Mobile-viewport screenshot collector for the gambling content detection dataset"
requires-python = ">=3.12"
dependencies = ["playwright>=1.47", "tldextract>=5.1", "Pillow>=10.4"]

[project.scripts]
crawler = "crawler.__main__:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: requirements.txt와 .env.example 작성**

```text
playwright>=1.47
tldextract>=5.1
Pillow>=10.4
pytest>=8.3
pytest-asyncio>=0.24
```

```text
# 수집 결과 루트 (없으면 /Users/seongmin/Downloads/논문 관련/dataset)
CRAWLER_OUT=/Users/seongmin/Downloads/논문 관련/dataset
# 도메인 해시 솔트. 임의의 긴 문자열. 없으면 실행이 거부된다.
CRAWLER_SALT=change-me-to-a-long-random-string
```

- [ ] **Step 3: 패키지 파일 생성**

`src/crawler/__init__.py`:
```python
"""도박 화면 데이터셋 수집기."""
__version__ = "0.1.0"
```
`tests/__init__.py`: 빈 파일.

- [ ] **Step 4: 가상환경·의존성·Chromium 설치**

Run:
```bash
cd /Users/seongmin/Downloads/gambling-content-detection
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt && .venv/bin/pip install -q -e .
.venv/bin/playwright install chromium
.venv/bin/python -c "import crawler, playwright, tldextract, PIL; print('ok', crawler.__version__)"
```
Expected: `ok 0.1.0`

- [ ] **Step 5: 빈 테스트 실행으로 pytest 설정 확인**

Run: `.venv/bin/pytest -q`
Expected: `no tests ran` (exit 5) — 오류 없이 수집만 되면 통과.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt .env.example src/crawler/__init__.py tests/__init__.py
git commit -m "chore: scaffold crawler package with playwright toolchain

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: domains — 등록 도메인·해시·URL 정규화

**Files:**
- Create: `src/crawler/domains.py`, `tests/test_domains.py`

**Interfaces:**
- Produces: `registrable_domain(url: str) -> str`, `domain_hash(domain: str, salt: str) -> str` (12 hex), `normalize_url(url: str) -> str`, `host_of(url) -> str`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_domains.py
from crawler.domains import registrable_domain, domain_hash, normalize_url, host_of


def test_registrable_domain_strips_subdomains():
    assert registrable_domain("https://www.seoul005.gtli.co.kr/a") == "gtli.co.kr"
    assert registrable_domain("http://sub.example.com") == "example.com"


def test_registrable_domain_for_ip_returns_ip():
    assert registrable_domain("http://127.0.0.1:8000/x") == "127.0.0.1"


def test_domain_hash_is_12_hex_and_salted():
    h1 = domain_hash("example.com", "salt-a")
    h2 = domain_hash("example.com", "salt-b")
    assert len(h1) == 12 and all(c in "0123456789abcdef" for c in h1)
    assert h1 != h2
    assert h1 == domain_hash("example.com", "salt-a")


def test_normalize_url_drops_fragment_and_tracking_params():
    u = "HTTP://Example.COM/path?utm_source=x&b=2&fbclid=1&a=1#frag"
    assert normalize_url(u) == "http://example.com/path?b=2&a=1"


def test_normalize_url_adds_scheme_and_keeps_bare_path():
    assert normalize_url("example.com") == "http://example.com/"
    assert normalize_url("https://example.com/x?") == "https://example.com/x"


def test_host_of():
    assert host_of("https://WWW.Warning.or.kr/i.html") == "www.warning.or.kr"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_domains.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'crawler.domains'`

- [ ] **Step 3: 구현**

```python
# src/crawler/domains.py
"""등록 도메인 추출, 도메인 해시, URL 정규화."""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

# suffix_list_urls=() → 네트워크 없이 패키지에 내장된 공개 접미사 목록만 사용
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "igshid"}


def _with_scheme(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        return "http://" + url
    return url


def host_of(url: str) -> str:
    return (urlsplit(_with_scheme(url)).hostname or "").lower()


def registrable_domain(url: str) -> str:
    ext = _EXTRACT(_with_scheme(url))
    if ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return (ext.domain or host_of(url)).lower()


def domain_hash(domain: str, salt: str) -> str:
    return hashlib.sha256((salt + domain).encode("utf-8")).hexdigest()[:12]


def normalize_url(url: str) -> str:
    parts = urlsplit(_with_scheme(url))
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_domains.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/crawler/domains.py tests/test_domains.py
git commit -m "feat(crawler): registrable domain, salted hash and url normalization

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: seeds — 시드 CSV 읽기, 후보 추가, 플랫폼 제외

**Files:**
- Create: `src/crawler/seeds.py`, `tests/test_seeds.py`

**Interfaces:**
- Consumes: `registrable_domain` (Task 2)
- Produces: `Seed(url, source, added_at, note)`, `HEADER`, `PLATFORM_BLOCKLIST`, `read_seeds(path) -> list[Seed]`, `seed_domains(paths) -> set[str]`, `load_blocklist(path) -> set[str]`, `is_platform(domain) -> bool`, `append_candidates(path, urls, source, known_domains, blocklist=frozenset()) -> list[str]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_seeds.py
from pathlib import Path

from crawler.seeds import (
    HEADER, Seed, append_candidates, is_platform, load_blocklist, read_seeds, seed_domains,
)


def write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_read_seeds_dedups_by_registrable_domain_and_skips_blank(tmp_path):
    p = write(tmp_path / "g.csv",
              "url,source,added_at,note\n"
              "https://a.example.com/,manual,2026-09-30,\n"
              "https://b.example.com/x,manual,2026-09-30,dup domain\n"
              ",manual,2026-09-30,blank\n"
              "https://other.net/,search:토토,2026-09-30,\n")
    seeds = read_seeds(p)
    assert [s.url for s in seeds] == ["https://a.example.com/", "https://other.net/"]
    assert seeds[1] == Seed(url="https://other.net/", source="search:토토", added_at="2026-09-30", note="")


def test_read_seeds_missing_file_returns_empty(tmp_path):
    assert read_seeds(tmp_path / "none.csv") == []


def test_seed_domains_unions_files(tmp_path):
    a = write(tmp_path / "a.csv", "url,source,added_at,note\nhttps://x.com/,m,d,\n")
    b = write(tmp_path / "b.csv", "url,source,added_at,note\nhttps://www.y.co.kr/,m,d,\n")
    assert seed_domains([a, b, tmp_path / "missing.csv"]) == {"x.com", "y.co.kr"}


def test_is_platform():
    assert is_platform("naver.com") and is_platform("t.me")
    assert not is_platform("toto-site.com")


def test_load_blocklist_ignores_comments(tmp_path):
    p = write(tmp_path / "block.txt", "# 절대 열지 않을 도메인\nadult-example.com\n\n  bad.net  \n")
    assert load_blocklist(p) == {"adult-example.com", "bad.net"}


def test_append_candidates_creates_file_and_dedups(tmp_path):
    out = tmp_path / "candidates.csv"
    added = append_candidates(
        out,
        ["https://new1.com/a", "https://www.new1.com/b", "https://naver.com/x", "https://known.com/", "https://blocked.com/"],
        source="community:verify.com",
        known_domains={"known.com"},
        blocklist={"blocked.com"},
    )
    assert added == ["https://new1.com/a"]
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(HEADER)
    assert lines[1].startswith("https://new1.com/a,community:verify.com,")
    # 두 번째 호출: 파일에 이미 있는 도메인은 다시 추가되지 않는다
    assert append_candidates(out, ["https://sub.new1.com/"], "search:x", set()) == []
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_seeds.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# src/crawler/seeds.py
"""시드 CSV 읽기·쓰기, 등록 도메인 기준 중복 제거, 플랫폼 제외 목록."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .domains import registrable_domain

HEADER = ["url", "source", "added_at", "note"]

PLATFORM_BLOCKLIST = frozenset({
    "naver.com", "google.com", "kakao.com", "daum.net", "youtube.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "t.me", "telegram.org", "tistory.com",
    "blogspot.com", "wikipedia.org", "apple.com", "microsoft.com", "cloudflare.com",
})


@dataclass(frozen=True)
class Seed:
    url: str
    source: str
    added_at: str
    note: str = ""


def is_platform(domain: str) -> bool:
    return domain in PLATFORM_BLOCKLIST


def read_seeds(path: Path) -> list[Seed]:
    path = Path(path)
    if not path.exists():
        return []
    seen: set[str] = set()
    out: list[Seed] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            dom = registrable_domain(url)
            if dom in seen:
                continue
            seen.add(dom)
            out.append(Seed(url=url, source=(row.get("source") or "").strip(),
                            added_at=(row.get("added_at") or "").strip(), note=(row.get("note") or "").strip()))
    return out


def seed_domains(paths: Iterable[Path]) -> set[str]:
    doms: set[str] = set()
    for p in paths:
        doms.update(registrable_domain(s.url) for s in read_seeds(Path(p)))
    return doms


def load_blocklist(path: Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    return {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def append_candidates(path: Path, urls: Iterable[str], source: str, known_domains: set[str],
                      blocklist: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """새 등록 도메인의 URL만 candidates 파일에 추가하고 추가된 URL 목록을 돌려준다."""
    path = Path(path)
    existing = {registrable_domain(s.url) for s in read_seeds(path)}
    skip = set(known_domains) | existing | set(blocklist)
    added: list[str] = []
    rows: list[list[str]] = []
    today = date.today().isoformat()
    for url in urls:
        dom = registrable_domain(url)
        if not dom or dom in skip or is_platform(dom):
            continue
        skip.add(dom)
        added.append(url)
        rows.append([url, source, today, "unverified"])
    if not rows:
        return added
    new_file = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(HEADER)
        writer.writerows(rows)
    return added
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_seeds.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/crawler/seeds.py tests/test_seeds.py
git commit -m "feat(crawler): seed csv reader and candidate writer with platform exclusions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: blocked — 차단 안내 페이지 판정

**Files:**
- Create: `src/crawler/blocked.py`, `tests/test_blocked.py`

**Interfaces:**
- Consumes: `host_of` (Task 2)
- Produces: `is_blocked_kr(final_url: str, body_text: str) -> bool`, `BLOCKED_HOSTS`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_blocked.py
from crawler.blocked import is_blocked_kr


def test_blocked_by_host():
    assert is_blocked_kr("https://www.warning.or.kr/i.html", "")
    assert is_blocked_kr("http://warning.or.kr/", "아무 내용")


def test_blocked_by_notice_text():
    body = "불법·유해정보(사이트)에 대한 차단 안내 ... 이 사이트는 접속이 차단되었습니다."
    assert is_blocked_kr("https://some-toto.com/", body)


def test_blocked_by_kcsc_and_block_word():
    assert is_blocked_kr("https://x.com/", "방송통신심의위원회의 심의 결과에 따라 차단된 페이지입니다")


def test_not_blocked_normal_page():
    assert not is_blocked_kr("https://news.example.com/", "방송통신심의위원회가 회의를 열었다")  # '차단' 없음
    assert not is_blocked_kr("https://toto.example/", "첫 충전 100% 보너스")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_blocked.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# src/crawler/blocked.py
"""국내 망의 불법 사이트 차단 안내 페이지(warning.or.kr) 판정."""
from __future__ import annotations

from .domains import host_of

BLOCKED_HOSTS = frozenset({"warning.or.kr", "www.warning.or.kr"})
_NOTICE = "불법·유해정보(사이트)에 대한 차단 안내"
_KCSC = "방송통신심의위원회"


def is_blocked_kr(final_url: str, body_text: str) -> bool:
    if host_of(final_url) in BLOCKED_HOSTS:
        return True
    text = body_text or ""
    if _NOTICE in text:
        return True
    return _KCSC in text and "차단" in text
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_blocked.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/crawler/blocked.py tests/test_blocked.py
git commit -m "feat(crawler): detect korean ISP block notice pages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: banners — 추출 JS와 배너 후보 필터

**Files:**
- Create: `src/crawler/banners.py`, `tests/test_banners.py`

**Interfaces:**
- Consumes: `registrable_domain` (Task 2)
- Produces: `BANNER_JS: str`(브라우저에서 `page.evaluate(BANNER_JS)`로 실행), `Candidate` dataclass(`tag,x,y,w,h,visible,src,href`), `from_js(items: list[dict]) -> list[Candidate]`, `iou(a, b) -> float`, `href_domain(c) -> str | None`, `filter_candidates(cands, page_domain, label, max_n=12) -> list[Candidate]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_banners.py
from crawler.banners import BANNER_JS, Candidate, filter_candidates, from_js, href_domain, iou


def c(w, h, x=0, y=0, href=None, visible=True, tag="img"):
    return Candidate(tag=tag, x=x, y=y, w=w, h=h, visible=visible, src="s.png", href=href)


def test_from_js_maps_dicts():
    items = [{"tag": "img", "x": 1, "y": 2, "w": 300, "h": 100, "visible": True, "src": "a.png", "href": None}]
    assert from_js(items) == [Candidate("img", 1, 2, 300, 100, True, "a.png", None)]


def test_size_and_aspect_rules():
    kept = filter_candidates([
        c(300, 100),            # ok
        c(140, 100),            # 너비 < 150
        c(300, 30),             # 높이 < 40
        c(150, 79),             # 면적 < 12000
        c(1000, 50),            # 비율 20 > 8
        c(60, 400),             # 비율 0.15 < 0.2 (너비도 미달)
        c(300, 100, visible=False),
    ], page_domain="site.com", label="gambling")
    assert kept == [c(300, 100)]


def test_iou_dedup_keeps_larger_and_sorts_by_area():
    a = c(400, 100, x=0, y=0)
    a_dup = c(380, 100, x=10, y=0)      # a와 크게 겹침 → 제거
    b = c(300, 200, x=0, y=500)         # 면적 60000 → 첫 번째
    kept = filter_candidates([a, a_dup, b], "site.com", "gambling")
    assert kept == [b, a]
    assert iou(a, a_dup) >= 0.8


def test_max_n():
    cands = [c(300, 100, y=i * 200) for i in range(20)]
    assert len(filter_candidates(cands, "site.com", "gambling", max_n=12)) == 12


def test_embedded_banner_keeps_only_external_hrefs():
    internal = c(300, 100, y=0, href="https://www.site.com/event")
    external = c(300, 100, y=300, href="https://toto-x.com/join")
    none = c(300, 100, y=600)
    assert filter_candidates([internal, external, none], "site.com", "embedded_banner") == [external]
    assert href_domain(external) == "toto-x.com" and href_domain(none) is None


def test_banner_js_is_a_function_expression():
    assert BANNER_JS.lstrip().startswith("() =>") and "getBoundingClientRect" in BANNER_JS
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_banners.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# src/crawler/banners.py
"""배너 후보 추출(브라우저 JS)과 필터(순수 함수)."""
from __future__ import annotations

from dataclasses import dataclass

from .domains import registrable_domain

# 페이지 좌표(스크롤 보정) 기준 bbox와 src/href를 뽑는다. 요소 핸들은 돌려주지 않는다.
BANNER_JS = r"""() => {
  const out = [];
  const els = document.querySelectorAll('img, iframe, [style*="background-image"]');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const cs = window.getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && cs.visibility !== 'hidden'
      && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0;
    let src = null;
    if (el.tagName === 'IMG') src = el.currentSrc || el.src || null;
    else if (el.tagName === 'IFRAME') src = el.src || null;
    else {
      const m = /url\(["']?([^"')]+)["']?\)/.exec(cs.backgroundImage || '');
      src = m ? m[1] : null;
    }
    const a = el.closest('a[href]');
    out.push({ tag: el.tagName.toLowerCase(), x: r.left + window.scrollX, y: r.top + window.scrollY,
               w: r.width, h: r.height, visible, src, href: a ? a.href : null });
  }
  return out;
}"""

MIN_W, MIN_H, MIN_AREA = 150, 40, 12_000
MIN_ASPECT, MAX_ASPECT = 0.2, 8.0
IOU_DUP = 0.8


@dataclass(frozen=True)
class Candidate:
    tag: str
    x: float
    y: float
    w: float
    h: float
    visible: bool
    src: str | None
    href: str | None

    @property
    def area(self) -> float:
        return self.w * self.h


def from_js(items: list[dict]) -> list[Candidate]:
    return [Candidate(tag=str(i.get("tag", "")), x=float(i.get("x", 0)), y=float(i.get("y", 0)),
                      w=float(i.get("w", 0)), h=float(i.get("h", 0)), visible=bool(i.get("visible", False)),
                      src=i.get("src"), href=i.get("href")) for i in items]


def iou(a: Candidate, b: Candidate) -> float:
    ix = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def href_domain(c: Candidate) -> str | None:
    return registrable_domain(c.href) if c.href else None


def _passes_size(c: Candidate) -> bool:
    if not c.visible or c.w < MIN_W or c.h < MIN_H or c.area < MIN_AREA:
        return False
    aspect = c.w / c.h if c.h else 0
    return MIN_ASPECT <= aspect <= MAX_ASPECT


def filter_candidates(cands: list[Candidate], page_domain: str, label: str, max_n: int = 12) -> list[Candidate]:
    pool = [c for c in cands if _passes_size(c)]
    if label == "embedded_banner":
        pool = [c for c in pool if c.href and href_domain(c) != page_domain]
    pool.sort(key=lambda c: c.area, reverse=True)
    kept: list[Candidate] = []
    for c in pool:
        if any(iou(c, k) >= IOU_DUP for k in kept):
            continue
        kept.append(c)
        if len(kept) >= max_n:
            break
    return kept
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_banners.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/crawler/banners.py tests/test_banners.py
git commit -m "feat(crawler): banner candidate extraction script and filter rules

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: store — 경로, meta/index 기록, 재실행 판단, 퍼셉추얼 해시

**Files:**
- Create: `src/crawler/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `domain_hash`, `normalize_url` (Task 2)
- Produces: `Store(root: Path, salt: str)` with `domain_dir(label, domain) -> Path`, `hash_of(domain) -> str`, `record(meta: dict) -> None`, `load_index() -> list[dict]`, `ok_count(label, domain) -> int`, `seen_recently(url, days=7, now=None) -> bool`, `find_duplicate(label, domain, phash, threshold=5) -> str | None`; module functions `ahash(path) -> str`, `hamming(a, b) -> int`, `now_kst() -> datetime`, `ts_label(dt) -> str` (예: `20260930T203512`).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_store.py
from datetime import datetime, timedelta, timezone

from PIL import Image

from crawler.store import Store, ahash, hamming, ts_label

KST = timezone(timedelta(hours=9))


def meta(label="gambling", domain="a.com", status="ok", url="https://a.com/", phash="0" * 64, at=None):
    at = at or datetime(2026, 9, 30, 20, 0, tzinfo=KST)
    return {"id": f"x_{ts_label(at)}", "label": label, "domain": domain, "status": status, "url": url,
            "url_norm": url, "phash": phash, "captured_at": at.isoformat()}


def test_domain_dir_uses_salted_hash(tmp_path):
    s = Store(tmp_path, "salt")
    d = s.domain_dir("gambling", "a.com")
    assert d.parent.name == "gambling" and len(d.name) == 12 and d.name == s.hash_of("a.com")


def test_record_appends_to_meta_and_index_and_counts(tmp_path):
    s = Store(tmp_path, "salt")
    s.record(meta()); s.record(meta(status="blocked_kr", url="https://a.com/b"))
    assert (tmp_path / "index.jsonl").read_text().count("\n") == 2
    assert (s.domain_dir("gambling", "a.com") / "meta.jsonl").exists()
    assert s.ok_count("gambling", "a.com") == 1
    # 새 인스턴스가 디스크에서 다시 읽어도 같다
    assert Store(tmp_path, "salt").ok_count("gambling", "a.com") == 1


def test_seen_recently_window(tmp_path):
    s = Store(tmp_path, "salt")
    old = datetime(2026, 9, 1, tzinfo=KST); recent = datetime(2026, 9, 29, tzinfo=KST)
    s.record(meta(url="https://a.com/old", at=old)); s.record(meta(url="https://a.com/new", at=recent))
    now = datetime(2026, 9, 30, tzinfo=KST)
    assert s.seen_recently("https://a.com/new#frag", now=now)
    assert not s.seen_recently("https://a.com/old", now=now)
    assert not s.seen_recently("https://a.com/never", now=now)


def test_ahash_hamming_and_duplicate(tmp_path):
    p1, p2, p3 = tmp_path / "1.png", tmp_path / "2.png", tmp_path / "3.png"
    Image.new("RGB", (400, 800), (255, 255, 255)).save(p1)
    im = Image.new("RGB", (400, 800), (255, 255, 255)); im.paste((0, 0, 0), (0, 0, 40, 40)); im.save(p2)  # 거의 같음
    Image.effect_noise((400, 800), 128).convert("RGB").save(p3)  # 전혀 다름
    h1, h2, h3 = ahash(p1), ahash(p2), ahash(p3)
    assert len(h1) == 64 and hamming(h1, h2) <= 5 < hamming(h1, h3)
    s = Store(tmp_path, "salt")
    s.record(meta(phash=h1))
    assert s.find_duplicate("gambling", "a.com", h2) == meta()["id"]
    assert s.find_duplicate("gambling", "a.com", h3) is None
    assert s.find_duplicate("normal", "a.com", h2) is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# src/crawler/store.py
"""저장 경로 규칙, meta/index JSONL 기록, 재실행 판단, 퍼셉추얼 해시."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from .domains import domain_hash, normalize_url

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def ts_label(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def ahash(path: Path, size: int = 16) -> str:
    im = Image.open(path).convert("L").resize((size, size), Image.Resampling.LANCZOS)
    px = list(im.getdata())
    avg = sum(px) / len(px)
    bits = "".join("1" if p > avg else "0" for p in px)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class Store:
    def __init__(self, root: Path, salt: str):
        self.root = Path(root)
        self.salt = salt
        self.index_path = self.root / "index.jsonl"
        self._index: list[dict] = self.load_index()

    def hash_of(self, domain: str) -> str:
        return domain_hash(domain, self.salt)

    def domain_dir(self, label: str, domain: str) -> Path:
        return self.root / label / self.hash_of(domain)

    def load_index(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        rows = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def record(self, meta: dict) -> None:
        d = self.domain_dir(meta["label"], meta["domain"])
        d.mkdir(parents=True, exist_ok=True)
        line = json.dumps(meta, ensure_ascii=False)
        with (d / "meta.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.root.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._index.append(meta)

    def ok_count(self, label: str, domain: str) -> int:
        return sum(1 for m in self._index if m["label"] == label and m["domain"] == domain and m["status"] == "ok")

    def seen_recently(self, url: str, days: int = 7, now: datetime | None = None) -> bool:
        now = now or now_kst()
        target = normalize_url(url)
        for m in self._index:
            if m.get("url_norm") != target:
                continue
            at = datetime.fromisoformat(m["captured_at"])
            if now - at <= timedelta(days=days):
                return True
        return False

    def find_duplicate(self, label: str, domain: str, phash: str, threshold: int = 5) -> str | None:
        for m in self._index:
            if m["label"] == label and m["domain"] == domain and m["status"] == "ok" and m.get("phash"):
                if hamming(m["phash"], phash) <= threshold:
                    return m["id"]
        return None
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/crawler/store.py tests/test_store.py
git commit -m "feat(crawler): jsonl store with resume checks and perceptual hash dedup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: config + browser — 설정 로더와 Playwright 컨텍스트 팩토리

**Files:**
- Create: `src/crawler/config.py`, `src/crawler/browser.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `Settings` dataclass(`out_root: Path, salt: str, per_domain=4, max_domains=300, concurrency=3, page_timeout_ms=20000, idle_timeout_ms=5000, settle_ms=1500, max_page_height=15000, device="Pixel 7", delays: dict[str,float], robots_labels: frozenset`), `DEFAULT_OUT`, `read_env_file(path) -> dict`, `load_settings(out=None, env=None, env_file=Path(".env"), **overrides) -> Settings`(솔트 없으면 `SystemExit`), `USER_AGENT`(robots 확인용), `async new_context(pw, browser, settings) -> BrowserContext`, `async open_browser(pw) -> Browser`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_config.py
from pathlib import Path

import pytest

from crawler.config import DEFAULT_OUT, Settings, load_settings, read_env_file


def test_read_env_file_parses_key_values_and_ignores_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# c\nCRAWLER_SALT=abc def\nCRAWLER_OUT=/tmp/x\n\nBAD LINE\n", encoding="utf-8")
    assert read_env_file(p) == {"CRAWLER_SALT": "abc def", "CRAWLER_OUT": "/tmp/x"}


def test_load_settings_requires_salt(tmp_path):
    with pytest.raises(SystemExit):
        load_settings(env={}, env_file=tmp_path / "none")


def test_load_settings_precedence_cli_over_env_over_default(tmp_path):
    envf = tmp_path / ".env"; envf.write_text("CRAWLER_SALT=s\nCRAWLER_OUT=/from/envfile\n", encoding="utf-8")
    s = load_settings(env={}, env_file=envf)
    assert s.out_root == Path("/from/envfile") and s.salt == "s"
    s2 = load_settings(env={"CRAWLER_OUT": "/from/env", "CRAWLER_SALT": "s"}, env_file=tmp_path / "none")
    assert s2.out_root == Path("/from/env")
    s3 = load_settings(out="/from/cli", env={"CRAWLER_SALT": "s"}, env_file=tmp_path / "none", per_domain=2)
    assert s3.out_root == Path("/from/cli") and s3.per_domain == 2
    s4 = load_settings(env={"CRAWLER_SALT": "s"}, env_file=tmp_path / "none")
    assert s4.out_root == DEFAULT_OUT


def test_defaults_match_spec():
    s = Settings(out_root=Path("/x"), salt="s")
    assert (s.per_domain, s.max_domains, s.concurrency, s.page_timeout_ms, s.settle_ms, s.max_page_height) == (4, 300, 3, 20000, 1500, 15000)
    assert s.delays == {"gambling": 3.0, "embedded_banner": 3.0, "hard_negative": 5.0, "normal": 5.0}
    assert s.robots_labels == frozenset({"hard_negative", "normal"}) and s.device == "Pixel 7"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: config.py 구현**

```python
# src/crawler/config.py
"""실행 설정. 우선순위: CLI 인자 > 환경변수/.env > 기본값."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_OUT = Path("/Users/seongmin/Downloads/논문 관련/dataset")
LABELS = ("gambling", "embedded_banner", "hard_negative", "normal")


@dataclass
class Settings:
    out_root: Path
    salt: str
    per_domain: int = 4
    max_domains: int = 300
    concurrency: int = 3
    page_timeout_ms: int = 20_000
    idle_timeout_ms: int = 5_000
    settle_ms: int = 1_500
    max_page_height: int = 15_000
    device: str = "Pixel 7"
    delays: dict[str, float] = field(default_factory=lambda: {
        "gambling": 3.0, "embedded_banner": 3.0, "hard_negative": 5.0, "normal": 5.0})
    robots_labels: frozenset[str] = frozenset({"hard_negative", "normal"})


def read_env_file(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def load_settings(out: str | None = None, env: Mapping[str, str] | None = None,
                  env_file: Path = Path(".env"), **overrides) -> Settings:
    env = dict(env if env is not None else os.environ)
    merged = {**read_env_file(env_file), **env}   # 실제 환경변수가 .env보다 우선
    salt = merged.get("CRAWLER_SALT", "").strip()
    if not salt:
        raise SystemExit("CRAWLER_SALT가 없습니다. .env(.env.example 참고) 또는 환경변수로 지정하세요.")
    root = Path(out) if out else Path(merged["CRAWLER_OUT"]) if merged.get("CRAWLER_OUT") else DEFAULT_OUT
    clean = {k: v for k, v in overrides.items() if v is not None}
    return Settings(out_root=root, salt=salt, **clean)
```

- [ ] **Step 4: browser.py 구현** (테스트는 Task 8 통합 테스트가 담당)

```python
# src/crawler/browser.py
"""Playwright 컨텍스트 팩토리: 기기 프로필, 요청 차단, 팝업·다이얼로그·다운로드 처리."""
from __future__ import annotations

import asyncio

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route

from .config import Settings

BLOCKED_RESOURCE_TYPES = frozenset({"media", "font"})
USER_AGENT = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Mobile Safari/537.36"


async def open_browser(pw: Playwright) -> Browser:
    return await pw.chromium.launch(headless=True)


async def _block_resources(route: Route) -> None:
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


async def _close_popup(page: Page) -> None:
    try:
        if await page.opener() is not None:
            await page.close()
    except Exception:
        pass


def _dismiss_dialog(dialog) -> None:
    asyncio.ensure_future(dialog.dismiss())


async def new_context(pw: Playwright, browser: Browser, settings: Settings) -> BrowserContext:
    device = dict(pw.devices[settings.device])
    context = await browser.new_context(
        **device, locale="ko-KR", timezone_id="Asia/Seoul",
        accept_downloads=False, ignore_https_errors=True,
    )
    context.set_default_timeout(settings.page_timeout_ms)
    await context.route("**/*", _block_resources)
    context.on("page", lambda p: asyncio.ensure_future(_close_popup(p)))
    return context


def attach_page_guards(page: Page) -> None:
    page.on("dialog", _dismiss_dialog)
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/pytest tests/test_config.py -q && .venv/bin/python -c "import crawler.browser; print('browser ok')"`
Expected: 4 passed, `browser ok`

- [ ] **Step 6: Commit**

```bash
git add src/crawler/config.py src/crawler/browser.py tests/test_config.py
git commit -m "feat(crawler): settings loader and hardened playwright context factory

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: capture — 페이지 파이프라인, 도메인 순회, 통합 테스트

**Files:**
- Create: `src/crawler/capture.py`, `tests/test_capture.py`(순수 함수), `tests/test_capture_integration.py`, `tests/fixtures/site/index.html`, `tests/fixtures/site/page2.html`, `tests/fixtures/site/page3.html`, `tests/fixtures/site/warning.html`

**Interfaces:**
- Consumes: Task 2~7 전부. `Seed`, `Store`, `Settings`, `new_context`, `attach_page_guards`, `BANNER_JS`, `from_js`, `filter_candidates`, `href_domain`, `is_blocked_kr`, `registrable_domain`, `normalize_url`, `ahash`, `now_kst`, `ts_label`
- Produces: `pick_internal_links(hrefs, page_domain, current_url, n) -> list[str]`, `robots_allows(url, user_agent) -> bool`, `async capture_page(page, url, *, label, seed_source, settings, store, idx) -> tuple[dict, list[str], list[str]]`(meta, 내부 링크, 배너 외부 도메인), `async capture_domain(context, seed, *, label, settings, store) -> tuple[list[dict], list[str]]`, `async run_capture(settings, seeds, *, label, emit_candidates=False, candidates_path=None, known_domains=frozenset()) -> dict`(요약 카운트)

- [ ] **Step 1: 순수 함수 테스트 작성**

```python
# tests/test_capture.py
from crawler.capture import pick_internal_links


def test_pick_internal_links_prefers_keywords_and_same_domain():
    hrefs = ["https://site.com/about", "https://other.com/x", "https://site.com/event/1", "https://www.site.com/notice",
             "https://site.com/", "https://site.com/about#top", "mailto:a@b.c", "https://site.com/casino"]
    got = pick_internal_links(hrefs, "site.com", current_url="https://site.com/", n=3)
    assert got == ["https://site.com/event/1", "https://www.site.com/notice", "https://site.com/casino"]


def test_pick_internal_links_falls_back_to_first_unique():
    hrefs = ["https://site.com/a", "https://site.com/a?x=1#f", "https://site.com/b"]
    assert pick_internal_links(hrefs, "site.com", current_url="https://site.com/", n=5) == ["https://site.com/a", "https://site.com/a?x=1", "https://site.com/b"]
```

- [ ] **Step 2: 픽스처 HTML 작성** (배너 이미지는 테스트가 실행 시 PNG로 생성)

`tests/fixtures/site/index.html`:
```html
<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>테스트 도박 사이트</title>
<style>body{margin:0;font-family:sans-serif} .b{display:block;margin:12px auto}</style></head>
<body>
<h1>실시간 스포츠 배팅 · 첫 충전 100% 보너스</h1>
<a href="https://toto-partner.example/join"><img class="b" src="banner1.png" width="360" height="90" alt="b1"></a>
<a href="/event/1"><img class="b" src="banner2.png" width="360" height="120" alt="b2"></a>
<img class="b" src="banner3.png" width="300" height="100" alt="b3">
<img src="icon.png" width="24" height="24" alt="icon">
<p style="height:1600px">긴 본문</p>
<img class="b" src="banner3.png" width="300" height="100" alt="lazy">
<nav><a href="/page2.html">이벤트 안내</a> <a href="/page3.html">공지</a> <a href="/about.html">소개</a> <a href="https://elsewhere.example/">외부</a></nav>
</body></html>
```
`tests/fixtures/site/page2.html`:
```html
<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>이벤트</title></head>
<body><h1>이벤트 페이지</h1><img src="banner2.png" width="360" height="120" alt="b2"></body></html>
```
`tests/fixtures/site/page3.html`:
```html
<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공지</title></head>
<body><h1>공지</h1><p>내용</p></body></html>
```
`tests/fixtures/site/warning.html`:
```html
<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>차단</title></head>
<body><h1>불법·유해정보(사이트)에 대한 차단 안내</h1><p>방송통신심의위원회의 심의 결과에 따라 차단되었습니다.</p></body></html>
```

- [ ] **Step 3: 통합 테스트 작성**

```python
# tests/test_capture_integration.py
import json
import shutil
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from crawler.capture import run_capture
from crawler.config import Settings
from crawler.seeds import Seed

FIXTURES = Path(__file__).parent / "fixtures" / "site"


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    shutil.copytree(FIXTURES, root)
    for name, size, color in [("banner1.png", (720, 180), (220, 30, 30)), ("banner2.png", (720, 240), (30, 30, 220)),
                              ("banner3.png", (600, 200), (30, 160, 30)), ("icon.png", (48, 48), (0, 0, 0))]:
        Image.new("RGB", size, color).save(root / name)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def fast_settings(tmp_path) -> Settings:
    return Settings(out_root=tmp_path / "dataset", salt="test-salt", per_domain=2, concurrency=1,
                    delays={"gambling": 0.0, "embedded_banner": 0.0, "hard_negative": 0.0, "normal": 0.0})


async def test_capture_saves_full_page_banners_and_index(site, tmp_path):
    settings = fast_settings(tmp_path)
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-09-30")], label="gambling")
    assert summary["ok"] == 2 and summary["error"] == 0
    rows = [json.loads(l) for l in (settings.out_root / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in rows] == ["ok", "ok"]
    home = rows[0]
    assert home["title"] == "테스트 도박 사이트" and home["viewport"] == {"width": 412, "height": 915, "dpr": 2}
    full = settings.out_root / home["full_path"]
    assert full.exists() and Image.open(full).size[0] == 824      # 412 css px × DPR 2
    assert 3 <= len(home["banners"]) <= 4                           # 24px 아이콘은 제외, 지연 로딩 배너 포함
    ext = [b for b in home["banners"] if b["external"]]
    assert ext and ext[0]["href_domain"] == "toto-partner.example"
    assert all((settings.out_root / b["path"]).exists() for b in home["banners"])
    assert rows[1]["url"].endswith(("/page2.html", "/page3.html"))   # 키워드(이벤트·공지) 우선
    assert (settings.out_root / "gambling" / home["domain_hash"] / "meta.jsonl").exists()


async def test_blocked_page_is_recorded_not_captured(site, tmp_path):
    settings = fast_settings(tmp_path)
    summary = await run_capture(settings, [Seed(url=site + "/warning.html", source="test", added_at="2026-09-30")], label="gambling")
    assert summary["blocked_kr"] == 1 and summary["ok"] == 0
    rows = [json.loads(l) for l in (settings.out_root / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "blocked_kr" and rows[0]["full_path"] is None
    assert not list((settings.out_root / "gambling").rglob("*.png"))


async def test_rerun_skips_domain_that_reached_per_domain(site, tmp_path):
    settings = fast_settings(tmp_path)
    seed = [Seed(url=site + "/", source="test", added_at="2026-09-30")]
    await run_capture(settings, seed, label="gambling")
    second = await run_capture(settings, seed, label="gambling")
    assert second["skipped_domains"] == 1 and second["ok"] == 0


async def test_emit_candidates_writes_external_banner_domains(site, tmp_path):
    settings = fast_settings(tmp_path)
    cand = tmp_path / "candidates.csv"
    await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-09-30")], label="embedded_banner",
                      emit_candidates=True, candidates_path=cand)
    text = cand.read_text(encoding="utf-8")
    assert "toto-partner.example" in text and "banner:" in text
```

- [ ] **Step 4: 실패 확인**

Run: `.venv/bin/pytest tests/test_capture.py tests/test_capture_integration.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'crawler.capture'`

- [ ] **Step 5: capture.py 구현**

```python
# src/crawler/capture.py
"""페이지 1개 처리 파이프라인과 도메인 순회, 동시 실행."""
from __future__ import annotations

import asyncio
import time
import urllib.robotparser
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


async def _scroll_through(page: Page, settings: Settings) -> int:
    height = int(await page.evaluate("document.documentElement.scrollHeight"))
    step = 915
    for y in range(0, min(height, settings.max_page_height), step):
        await page.evaluate(f"window.scrollTo(0, {y})")
        await page.wait_for_timeout(150)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(settings.settle_ms)
    return int(await page.evaluate("document.documentElement.scrollHeight"))


def _crop_banners(full_png: Path, cands, dpr: int, base: Path, stem: str, page_domain: str) -> list[dict]:
    out: list[dict] = []
    with Image.open(full_png) as im:
        W, H = im.size
        for k, c in enumerate(cands):
            box = (max(0, int(c.x * dpr)), max(0, int(c.y * dpr)), min(W, int((c.x + c.w) * dpr)), min(H, int((c.y + c.h) * dpr)))
            if box[2] - box[0] < 10 or box[3] - box[1] < 10:
                continue
            path = base / f"{stem}_b{k}.png"
            im.crop(box).save(path)
            hd = href_domain(c)
            out.append({"path": str(path.relative_to(base.parent.parent)), "bbox": [round(c.x), round(c.y), round(c.w), round(c.h)],
                        "tag": c.tag, "src": c.src, "href": c.href, "href_domain": hd,
                        "external": bool(hd and hd != page_domain)})
    return out


async def capture_page(page: Page, url: str, *, label: str, seed_source: str, settings: Settings,
                       store: Store, idx: int) -> tuple[dict, list[str], list[str]]:
    domain = registrable_domain(url)
    dhash = store.hash_of(domain)
    at = now_kst()
    stem = f"{ts_label(at)}_{idx}"
    ddir = store.domain_dir(label, domain)
    meta: dict = {"id": f"{dhash}_{stem}", "label": label, "seed_source": seed_source, "url": url,
                  "url_norm": normalize_url(url), "final_url": None, "domain": domain, "domain_hash": dhash,
                  "captured_at": at.isoformat(), "status": "error", "viewport": {"width": 412, "height": 915, "dpr": 2},
                  "title": None, "full_path": None, "page_height": None, "phash": None, "banners": [], "error": None}
    links: list[str] = []
    ext_domains: list[str] = []
    try:
        resp = None
        for attempt in range(2):
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                break
            except PWTimeout:
                if attempt == 1:
                    raise
        meta["final_url"] = page.url
        body_text = await page.evaluate("document.body ? document.body.innerText.slice(0, 20000) : ''")
        if is_blocked_kr(page.url, body_text):
            meta["status"] = "blocked_kr"
            return meta, links, ext_domains
        try:
            await page.wait_for_load_state("networkidle", timeout=settings.idle_timeout_ms)
        except PWTimeout:
            pass
        meta["page_height"] = await _scroll_through(page, settings)
        meta["title"] = await page.title()
        ddir.mkdir(parents=True, exist_ok=True)
        full = ddir / f"{stem}_full.png"
        await page.screenshot(path=str(full), full_page=True)
        dpr = 2
        with Image.open(full) as im:
            if im.height > settings.max_page_height * dpr:
                im.crop((0, 0, im.width, settings.max_page_height * dpr)).save(full)
        cands = filter_candidates(from_js(await page.evaluate(BANNER_JS)), domain, label)
        meta["banners"] = _crop_banners(full, cands, dpr, ddir, stem, domain)
        ext_domains = sorted({b["href"] for b in meta["banners"] if b["external"]})
        if idx == 0:
            hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            links = pick_internal_links(hrefs, domain, page.url, settings.per_domain - 1)
        meta["phash"] = ahash(full)
        dup = store.find_duplicate(label, domain, meta["phash"])
        if dup:
            meta["status"] = "duplicate"; meta["error"] = f"near-duplicate of {dup}"
            for b in meta["banners"]:
                (store.root / b["path"]).unlink(missing_ok=True)
            full.unlink(missing_ok=True)
            meta["banners"] = []
            return meta, links, ext_domains
        meta["full_path"] = str(full.relative_to(store.root))
        meta["status"] = "ok"
    except Exception as e:  # 페이지 단위 격리: 어떤 예외도 다음 페이지로 넘어간다
        meta["status"] = "error"
        meta["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return meta, links, ext_domains


async def capture_domain(context: BrowserContext, seed: Seed, *, label: str, settings: Settings,
                         store: Store) -> tuple[list[dict], list[str]]:
    domain = registrable_domain(seed.url)
    metas: list[dict] = []
    candidates: list[str] = []
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
                meta = {"id": f"{store.hash_of(domain)}_{ts_label(now_kst())}_{idx}", "label": label, "seed_source": seed.source,
                        "url": url, "url_norm": normalize_url(url), "final_url": None, "domain": domain,
                        "domain_hash": store.hash_of(domain), "captured_at": now_kst().isoformat(), "status": "robots_disallow",
                        "viewport": {"width": 412, "height": 915, "dpr": 2}, "title": None, "full_path": None,
                        "page_height": None, "phash": None, "banners": [], "error": None}
                store.record(meta); metas.append(meta); idx += 1
                continue
            started = time.monotonic()
            meta, links, ext = await capture_page(page, url, label=label, seed_source=seed.source, settings=settings, store=store, idx=idx)
            store.record(meta); metas.append(meta); candidates.extend(ext)
            if idx == 0 and meta["status"] == "error" and "net::ERR_NAME_NOT_RESOLVED" in (meta["error"] or ""):
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
    summary = {s: 0 for s in STATUSES}
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
    all_candidates: list[str] = []
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
        added = append_candidates(candidates_path, all_candidates, source=f"banner:{label}", known_domains=set(known_domains))
        summary["candidates_added"] = len(added)
    return summary
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/pytest tests/test_capture.py tests/test_capture_integration.py -q`
Expected: 6 passed (통합 4 + 순수 2). 첫 실행은 Chromium 기동으로 20~40초.

- [ ] **Step 7: Commit**

```bash
git add src/crawler/capture.py tests/test_capture.py tests/test_capture_integration.py tests/fixtures
git commit -m "feat(crawler): page capture pipeline with banner crops, block detection and resume

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: discover — 커뮤니티 링크 수집과 DuckDuckGo 검색 수집

**Files:**
- Create: `src/crawler/discover.py`, `tests/test_discover.py`

**Interfaces:**
- Consumes: `new_context`, `open_browser`, `attach_page_guards`, `read_seeds`, `append_candidates`, `seed_domains`, `registrable_domain`, `is_platform`
- Produces: `parse_ddg_links(html: str) -> list[str]`, `external_domains_urls(hrefs, page_domain) -> list[str]`(외부 등록 도메인당 첫 URL), `async discover_community(settings, community_csv, out_csv, known_domains) -> int`, `async discover_search(settings, keywords_path, out_csv, known_domains, per_keyword=20) -> int`, `DDG_URL`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_discover.py
from crawler.discover import external_domains_urls, parse_ddg_links

DDG_HTML = '''
<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftoto%2Dverify.example%2Flist&amp;rut=abc">토토 검증</a></div>
<div class="result"><a class="result__a" href="https://direct.example/page">직접 링크</a></div>
<div class="result"><a class="result__snippet" href="https://ignored.example/">snippet</a></div>
'''


def test_parse_ddg_links_resolves_uddg_and_keeps_order():
    assert parse_ddg_links(DDG_HTML) == ["https://toto-verify.example/list", "https://direct.example/page"]


def test_external_domains_urls_filters_same_domain_platform_and_dups():
    hrefs = ["https://verify.com/a", "https://www.site-a.com/x", "https://site-a.com/y", "https://naver.com/blog",
             "javascript:void(0)", "https://site-b.net/", "https://t.me/chan"]
    assert external_domains_urls(hrefs, "verify.com") == ["https://www.site-a.com/x", "https://site-b.net/"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_discover.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# src/crawler/discover.py
"""시드 확장: 검증 커뮤니티 페이지의 외부 링크, DuckDuckGo HTML 검색 결과."""
from __future__ import annotations

import asyncio
import html as htmllib
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from playwright.async_api import async_playwright

from .browser import attach_page_guards, new_context, open_browser
from .config import Settings
from .domains import registrable_domain
from .seeds import append_candidates, is_platform, read_seeds

DDG_URL = "https://html.duckduckgo.com/html/?q={q}&kl=kr-kr"
_RESULT_A = re.compile(r'<a[^>]*class="[^"]*\bresult__a\b[^"]*"[^>]*href="([^"]+)"', re.I)


def parse_ddg_links(html: str) -> list[str]:
    out: list[str] = []
    for raw in _RESULT_A.findall(html):
        href = htmllib.unescape(raw)
        if href.startswith("//"):
            href = "https:" + href
        q = parse_qs(urlsplit(href).query)
        target = q.get("uddg", [href])[0]
        if target.startswith(("http://", "https://")) and target not in out:
            out.append(target)
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
    keywords = [k.strip() for k in Path(keywords_path).read_text(encoding="utf-8").splitlines() if k.strip() and not k.startswith("#")]
    added_total = 0
    async with async_playwright() as pw:
        browser = await open_browser(pw)
        context = await new_context(pw, browser, settings)
        page = await context.new_page(); attach_page_guards(page)
        try:
            for kw in keywords:
                try:
                    await page.goto(DDG_URL.format(q=quote(kw)), wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                    links = parse_ddg_links(await page.content())[:per_keyword]
                except Exception as e:
                    print(f"[search] {kw}: {type(e).__name__}")
                    continue
                urls = external_domains_urls(links, "duckduckgo.com")
                added = append_candidates(out_csv, urls, source=f"search:{kw}", known_domains=known_domains)
                known_domains.update(registrable_domain(u) for u in added)
                added_total += len(added)
                print(f"[search] {kw}: 결과 {len(links)}개 중 {len(added)}개 추가")
                await asyncio.sleep(3.0)
        finally:
            await context.close(); await browser.close()
    return added_total
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_discover.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/crawler/discover.py tests/test_discover.py
git commit -m "feat(crawler): seed discovery from community pages and duckduckgo html search

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: stats + CLI + 시드 템플릿

**Files:**
- Create: `src/crawler/stats.py`, `src/crawler/__main__.py`, `tests/test_stats.py`, `tests/test_cli.py`, `seeds/README.md`, `seeds/gambling.csv`, `seeds/embedded_banner.csv`, `seeds/hard_negative.csv`, `seeds/normal.csv`, `seeds/community_lists.csv`, `seeds/candidates.csv`, `seeds/keywords.txt`, `seeds/blocklist.txt`

**Interfaces:**
- Consumes: 전 모듈
- Produces: `summarize(index_rows) -> dict[label, dict]`, `format_table(summary) -> str`, `build_parser() -> argparse.ArgumentParser`, `main(argv=None) -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_stats.py
from crawler.stats import format_table, summarize


def test_summarize_counts_domains_pages_banners_per_label():
    rows = [
        {"label": "gambling", "domain": "a.com", "status": "ok", "banners": [{}, {}]},
        {"label": "gambling", "domain": "a.com", "status": "duplicate", "banners": []},
        {"label": "gambling", "domain": "b.com", "status": "blocked_kr", "banners": []},
        {"label": "normal", "domain": "n.com", "status": "ok", "banners": [{}]},
    ]
    s = summarize(rows)
    assert s["gambling"] == {"domains": 2, "ok": 1, "blocked_kr": 1, "error": 0, "duplicate": 1, "robots_disallow": 0, "banners": 2}
    assert s["normal"]["banners"] == 1 and s["normal"]["domains"] == 1
    table = format_table(s)
    assert "gambling" in table and "blocked_kr" in table
```

```python
# tests/test_cli.py
from crawler.__main__ import build_parser


def test_capture_args():
    ns = build_parser().parse_args(["capture", "--label", "gambling", "--seeds", "seeds/gambling.csv", "--per-domain", "3", "--emit-candidates"])
    assert ns.command == "capture" and ns.label == "gambling" and ns.per_domain == 3 and ns.emit_candidates is True


def test_discover_subcommands():
    ns = build_parser().parse_args(["discover", "search", "--per-keyword", "5"])
    assert ns.command == "discover" and ns.kind == "search" and ns.per_keyword == 5
    ns2 = build_parser().parse_args(["discover", "community"])
    assert ns2.kind == "community"


def test_stats_default_out_is_none():
    assert build_parser().parse_args(["stats"]).out is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_stats.py tests/test_cli.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: stats.py 구현**

```python
# src/crawler/stats.py
"""index.jsonl 집계."""
from __future__ import annotations

from collections import defaultdict

STATUSES = ("ok", "blocked_kr", "error", "duplicate", "robots_disallow")


def summarize(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    domains: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        lab = r["label"]
        s = out.setdefault(lab, {"domains": 0, **{k: 0 for k in STATUSES}, "banners": 0})
        domains[lab].add(r["domain"])
        s[r["status"]] = s.get(r["status"], 0) + 1
        s["banners"] += len(r.get("banners") or [])
    for lab, s in out.items():
        s["domains"] = len(domains[lab])
    return out


def format_table(summary: dict[str, dict]) -> str:
    cols = ["label", "domains", *STATUSES, "banners"]
    lines = [" | ".join(f"{c:>15}" if c != "label" else f"{c:<16}" for c in cols)]
    lines.append("-" * len(lines[0]))
    for lab in sorted(summary):
        s = summary[lab]
        lines.append(" | ".join([f"{lab:<16}", *(f"{s.get(c, 0):>15}" for c in cols[1:])]))
    if len(lines) == 2:
        lines.append("(index.jsonl 없음 또는 비어 있음)")
    return "\n".join(lines)
```

- [ ] **Step 4: __main__.py 구현**

```python
# src/crawler/__main__.py
"""CLI: python -m crawler discover|capture|stats"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import LABELS, load_settings
from .discover import discover_community, discover_search
from .seeds import load_blocklist, read_seeds, seed_domains
from .stats import format_table, summarize
from .store import Store

SEEDS_DIR = Path("seeds")
ALL_SEED_FILES = [SEEDS_DIR / f"{lab}.csv" for lab in LABELS] + [SEEDS_DIR / "community_lists.csv", SEEDS_DIR / "candidates.csv"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crawler", description="도박 화면 데이터셋 수집기")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="시드 후보 수집 → seeds/candidates.csv")
    dk = d.add_subparsers(dest="kind", required=True)
    dc = dk.add_parser("community"); dc.add_argument("--seeds", default=str(SEEDS_DIR / "community_lists.csv")); dc.add_argument("--out", default=str(SEEDS_DIR / "candidates.csv"))
    ds = dk.add_parser("search"); ds.add_argument("--keywords", default=str(SEEDS_DIR / "keywords.txt")); ds.add_argument("--per-keyword", type=int, default=20); ds.add_argument("--out", default=str(SEEDS_DIR / "candidates.csv"))

    c = sub.add_parser("capture", help="시드 파일의 도메인을 캡처")
    c.add_argument("--label", required=True, choices=LABELS)
    c.add_argument("--seeds", required=True)
    c.add_argument("--out", default=None, help="저장 루트 (기본: .env CRAWLER_OUT 또는 /Users/seongmin/Downloads/논문 관련/dataset)")
    c.add_argument("--per-domain", type=int, default=None)
    c.add_argument("--max-domains", type=int, default=None)
    c.add_argument("--concurrency", type=int, default=None)
    c.add_argument("--emit-candidates", action="store_true", help="배너의 외부 링크 도메인을 seeds/candidates.csv에 추가")

    s = sub.add_parser("stats", help="라벨별 수집 현황"); s.add_argument("--out", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.command == "stats":
        settings = load_settings(out=ns.out)
        print(format_table(summarize(Store(settings.out_root, settings.salt).load_index())))
        return 0
    if ns.command == "discover":
        settings = load_settings()
        known = seed_domains(ALL_SEED_FILES)
        if ns.kind == "community":
            n = asyncio.run(discover_community(settings, Path(ns.seeds), Path(ns.out), known))
        else:
            n = asyncio.run(discover_search(settings, Path(ns.keywords), Path(ns.out), known, ns.per_keyword))
        print(f"후보 {n}개 추가 → {ns.out}. 검토 후 seeds/gambling.csv로 옮기세요.")
        return 0
    # capture
    from .capture import run_capture  # playwright import 지연
    settings = load_settings(out=ns.out, per_domain=ns.per_domain, max_domains=ns.max_domains, concurrency=ns.concurrency)
    seeds = read_seeds(Path(ns.seeds))
    blocklist = load_blocklist(SEEDS_DIR / "blocklist.txt")
    from .domains import registrable_domain
    seeds = [s for s in seeds if registrable_domain(s.url) not in blocklist]
    if not seeds:
        print(f"시드가 없습니다: {ns.seeds}"); return 1
    print(f"[{ns.label}] 도메인 {len(seeds)}개, 저장 루트 {settings.out_root}")
    summary = asyncio.run(run_capture(settings, seeds, label=ns.label, emit_candidates=ns.emit_candidates,
                                      candidates_path=SEEDS_DIR / "candidates.csv", known_domains=frozenset(seed_domains(ALL_SEED_FILES))))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 시드 템플릿 작성**

`seeds/gambling.csv`, `seeds/embedded_banner.csv`, `seeds/hard_negative.csv`, `seeds/normal.csv`, `seeds/community_lists.csv`, `seeds/candidates.csv` 모두 첫 줄만:
```csv
url,source,added_at,note
```
`seeds/keywords.txt`:
```text
# DuckDuckGo 검색 키워드. 한 줄에 하나.
토토사이트
안전놀이터
카지노사이트
메이저사이트
바카라사이트
슬롯사이트
먹튀검증
스포츠토토 사이트 추천
파워볼사이트
온라인카지노
```
`seeds/blocklist.txt`:
```text
# 어떤 경우에도 열지 않을 등록 도메인. 한 줄에 하나.
```
`seeds/README.md`:
```markdown
# 시드 파일

| 파일 | 용도 | 누가 채우나 |
|---|---|---|
| gambling.csv | 도박 사이트 (라벨 gambling) | candidates.csv를 검토해 사람이 옮김 |
| embedded_banner.csv | 무료 중계·웹툰 등 정상 서비스 속 도박 배너 | 사람이 직접 |
| hard_negative.csv | 합법 스포츠토토·경기정보·캐주얼 게임·주식 등 | 사람이 직접 |
| normal.csv | 뉴스·쇼핑·커뮤니티 일반 화면 | 사람이 직접 |
| community_lists.csv | 검증 커뮤니티 페이지 (discover community 입력) | 사람이 직접 |
| candidates.csv | 자동 발견 결과. **capture는 이 파일을 직접 읽지 않는다** | discover / capture --emit-candidates |
| keywords.txt | discover search 키워드 | 사람이 직접 |
| blocklist.txt | 어떤 경우에도 열지 않을 도메인 | 사람이 직접 |

컬럼: `url,source,added_at,note`. 같은 등록 도메인은 첫 줄만 쓰인다.

## 실행 순서

1. `.env`에 `CRAWLER_SALT`(긴 임의 문자열)와 필요하면 `CRAWLER_OUT`을 적는다.
2. `python -m crawler discover search` / `python -m crawler discover community` → candidates.csv
3. candidates.csv를 훑어 도박 사이트만 gambling.csv로 옮긴다(검증 커뮤니티 자체는 community_lists.csv로).
4. `python -m crawler capture --label embedded_banner --seeds seeds/embedded_banner.csv --emit-candidates`
5. `python -m crawler capture --label gambling --seeds seeds/gambling.csv`
6. `python -m crawler capture --label hard_negative --seeds seeds/hard_negative.csv` (robots.txt·5초 간격 자동 적용), normal도 같은 방식
7. `python -m crawler stats`
```

- [ ] **Step 6: 통과 확인과 CLI 스모크**

Run:
```bash
.venv/bin/pytest tests/test_stats.py tests/test_cli.py -q
CRAWLER_SALT=smoke .venv/bin/python -m crawler stats --out /tmp/crawler-smoke
CRAWLER_SALT=smoke .venv/bin/python -m crawler capture --label gambling --seeds seeds/gambling.csv --out /tmp/crawler-smoke; echo "exit=$?"
```
Expected: 4 passed; stats가 빈 표와 "(index.jsonl 없음 또는 비어 있음)" 출력; capture는 "시드가 없습니다" 후 exit=1.

- [ ] **Step 7: Commit**

```bash
git add src/crawler/stats.py src/crawler/__main__.py tests/test_stats.py tests/test_cli.py seeds
git commit -m "feat(crawler): cli with discover/capture/stats and seed templates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: README 사용법, 전체 테스트, 실기 스모크

**Files:**
- Modify: `README.md` (저장소 구조 표와 문서 표 사이에 "데이터 수집기" 절 추가)

- [ ] **Step 1: README에 절 추가** — `## 저장소 구조` 코드 블록 뒤에 삽입:

```markdown
## 데이터 수집기 (src/crawler)

모바일 뷰포트(Pixel 7)로 페이지를 렌더링해 전체 화면 스크린샷 + 배너 크롭 + 메타데이터를 저장한다. 설계: `docs/superpowers/specs/2026-09-23-gambling-crawler-design.md`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -e . && .venv/bin/playwright install chromium
cp .env.example .env   # CRAWLER_SALT를 임의의 긴 문자열로 바꾼다
.venv/bin/python -m crawler discover search            # 후보 → seeds/candidates.csv
.venv/bin/python -m crawler capture --label gambling --seeds seeds/gambling.csv
.venv/bin/python -m crawler stats
```

결과는 저장소 밖 `/Users/seongmin/Downloads/논문 관련/dataset/<label>/<도메인해시>/`에 쓰이고 `index.jsonl`이 전역 색인이다. 시드 작성법은 `seeds/README.md`.
```

- [ ] **Step 2: 전체 테스트**

Run: `.venv/bin/pytest -q`
Expected: 모든 테스트 통과 (약 33개).

- [ ] **Step 3: 실기 스모크 (외부 네트워크 1회, 정상 사이트만)**

`/tmp/smoke_normal.csv`:
```csv
url,source,added_at,note
https://www.wikipedia.org/,smoke,2026-09-30,공개 페이지 스모크
```
Run:
```bash
CRAWLER_SALT=smoke .venv/bin/python -m crawler capture --label normal --seeds /tmp/smoke_normal.csv --out /tmp/crawler-smoke --per-domain 1
CRAWLER_SALT=smoke .venv/bin/python -m crawler stats --out /tmp/crawler-smoke
ls /tmp/crawler-smoke/normal/*/
```
Expected: 요약에 `"ok": 1`, 폴더에 `*_full.png`와 `meta.jsonl`. 확인 후 `/tmp/crawler-smoke` 삭제.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: crawler usage in readme

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-Review (작성 후 점검)

- **스펙 커버리지**: 명령 3개(T9·T8·T10), 시드 파일·플랫폼 제외(T3·T10), 기기 프로필·요청 차단·팝업(T7), 페이지 처리 8단계·배너 규칙·차단 판정(T4·T5·T8), 저장 규격·해시·재실행·중복 제거(T6·T8), robots·간격·동시성(T8), 오류 처리(T8 예외 격리·DNS 중단), 테스트 전략(각 Task + T8 통합), 환경·의존성(T1), README(T10·T11). 스펙 5절의 "브라우저 프로세스가 죽으면 컨텍스트 재생성 후 1회 재시도"는 컨텍스트를 도메인마다 새로 만들고 페이지 예외를 격리하는 것으로 갈음한다(도메인 재시도는 재실행으로 자연 처리).
- **플레이스홀더**: 없음.
- **타입 일관성**: `Seed(url, source, added_at, note)`, `Store.record(meta)`, `Settings` 필드명, `run_capture(settings, seeds, *, label, emit_candidates, candidates_path, known_domains)`, `filter_candidates(cands, page_domain, label, max_n)`, `append_candidates(path, urls, source, known_domains, blocklist)`를 T3·T5·T6·T8·T9·T10에서 동일하게 사용.
