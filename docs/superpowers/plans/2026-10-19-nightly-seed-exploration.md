# 야간 수집 루프와 시드 탐색(nightly · explore · promote) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일 04:30 사람 손 없이 검색·커뮤니티 discover → 후보 선캡처(리뷰 루트) → 기존 시드 재캡처 → 보고서를 돌리고, 아침에 사람이 `review.csv` 판정을 적으면 `promote` 한 번으로 시드·데이터셋에 반영되게 한다.

**Architecture:** 기존 `src/crawler/` 패키지에 순수 모듈 2개(`keywords.py` 키워드 확장, `review.py` 신호·추천·review.csv)와 오케스트레이션 모듈 3개(`explore.py` 선캡처·시드 확장, `promote.py` 판정 반영, `nightly.py` 단계 실행기·보고서)를 더한다. 선캡처는 본 데이터셋과 분리된 리뷰 루트(`<CRAWLER_OUT>/_review`)에 같은 `Store` 규격으로 쓴다. 시간 예산은 `asyncio.wait_for` 로 걸고(이 Mac 엔 `timeout` 이 없다), launchd 가 `scripts/nightly.sh` 를 부른다.

**Tech Stack:** Python 3.12, Playwright 1.63(async, Chromium), tldextract, Pillow, pytest + pytest-asyncio(`asyncio_mode = "auto"`), zsh, launchd.

**Spec:** `docs/superpowers/specs/2026-10-19-nightly-seed-exploration-design.md` (선행 스펙 `docs/superpowers/specs/2026-09-23-gambling-crawler-design.md`)

## Global Constraints

- 저장소 루트 `/Users/seongmin/gambling-content-detection`, 가상환경 `.venv` (`.venv/bin/python`, `.venv/bin/pytest`). 모든 명령은 저장소 루트에서 실행한다. `python -m crawler` 는 editable 설치로 동작한다.
- 저장 루트 기본값 `/Users/seongmin/datasets/gambling` (10/19 이동 완료). 리뷰 루트 기본값 `<루트>/_review`, 환경변수 `CRAWLER_REVIEW` 로 변경 가능.
- 외부 pip 패키지를 새로 추가하지 않는다(의존성은 playwright·tldextract·Pillow 뿐).
- 새 코드는 기존 규약을 따른다: 모듈 첫 줄 한국어 docstring, `from __future__ import annotations`, 타입 힌트, csv 는 `lineterminator="\n"`, 시각은 `store.now_kst()` (KST).
- 밤당 상한(스펙 2절): 검색 키워드 10 수동 + 5 자동, 선캡처 새 후보 40 도메인, 커뮤니티 자동 등록 5개. 후보 라벨 `candidate` 는 robots.txt 준수 + 5초 간격 + 메뉴 클릭 없음.
- 단계 예산(분): search 12 · community 8 · explore 25 · capture 40, 전체 `--budget-min 90`. 종료 코드 0 정상 / 1 일부 실패·부분 / 2 실행 불가.
- 루프는 git 명령을 쓰지 않고 `seeds/` 와 `out/` 만 바꾼다. 자동 승격은 없다.
- 커밋 메시지는 기존 스타일(`feat(crawler): …`, `fix(crawler): …`, `chore(seeds): …`, `docs: …`)을 따르고 마지막 줄에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 를 붙인다. `.idea/caches/deviceStreaming.xml` 의 변경은 커밋하지 않는다(`git add` 에 경로를 명시).
- 테스트 전체 실행: `.venv/bin/pytest -q` (현재 52개, 약 40초). 각 Task 끝에 전체 통과를 확인한다.

---

## File Structure

| 파일 | 역할 |
|---|---|
| `src/crawler/config.py` (수정) | `DEFAULT_OUT` 변경, `CANDIDATE_LABEL`, `Settings` 에 재캡처·리뷰 루트·야간 상한·예산 필드, `CRAWLER_REVIEW` 읽기 |
| `src/crawler/seeds.py` (수정) | 시드 CSV 행 갱신 헬퍼(`update_notes`, `append_seed`, `remove_domain`, `update_source`), 키워드 파일 읽기·쓰기, `all_seed_files` |
| `src/crawler/store.py` (수정) | `ok_count(days)`, `blocked_recently`, `rows_for`, `remove_domain`, `adopt_domain`, `rewrite_index` |
| `src/crawler/capture.py` (수정) | meta `text_excerpt`·`ext_domains`, `recapture_days` 창, 최근 차단 도메인 건너뛰기, `run_capture(store=)` |
| `src/crawler/discover.py` (수정) | `SearchTally`(봇 확인 감지), `discover_search_keywords`(키워드 목록 입력·키워드별 수확 반환) |
| `src/crawler/keywords.py` (신규) | `extract_terms`, 상태 파일 `load_state`/`save_state`, `pick_auto_keywords`, `record_run`, `expand` |
| `src/crawler/review.py` (신규) | `signals`, `suggest`, `looks_like_community`, `ReviewRow`, `write_review_csv`, `read_review_csv`, `VERDICTS` |
| `src/crawler/explore.py` (신규) | `select_candidates`, `run_explore`(선캡처 → 신호 → 커뮤니티 자동 등록 → review.csv → note 갱신 → 키워드 확장) |
| `src/crawler/promote.py` (신규) | `plan_promotion`, `apply_promotion`, `run_promote` |
| `src/crawler/nightly.py` (신규) | `StageResult`, `Runner`, 잠금, `daily_counts`, `build_report`, `make_thumbs`, `prune_out` |
| `src/crawler/__main__.py` (수정) | 명령 `nightly`, `explore`, `promote`, `stats --review`, `capture --recapture-days` |
| `scripts/nightly.sh`, `scripts/launchd/com.gambling-crawler.nightly.plist`, `scripts/README.md` (신규) | launchd 진입점·일정·운영 문서 |
| `tests/test_config.py`, `tests/test_seeds.py`, `tests/test_store.py`, `tests/test_capture_integration.py`, `tests/test_discover.py`, `tests/test_cli.py` (수정) | 기존 테스트 확장 |
| `tests/test_keywords.py`, `tests/test_review.py`, `tests/test_explore.py`, `tests/test_promote.py`, `tests/test_nightly.py` (신규), `tests/fixtures/site/community.html` (신규) | 새 모듈 테스트와 커뮤니티 픽스처 |
| `.gitignore`, `.env.example`, `seeds/README.md` (수정) | `out/` 제외, 새 경로, 운영 순서 |

---

### Task 1: config — 새 설정 필드, 리뷰 루트, 저장 루트 기본값

**Files:**
- Modify: `src/crawler/config.py`
- Modify: `.env.example`, `.gitignore`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `CANDIDATE_LABEL = "candidate"`, `Settings.recapture_days: int`, `Settings.skip_blocked_days: int`, `Settings.review_root: Path`, `Settings.nightly_search_auto / nightly_max_candidates / nightly_candidate_pages / nightly_max_auto_communities: int`, `Settings.auto_keyword_pool / auto_keyword_add_per_day / auto_keyword_retire_streak: int`, `Settings.nightly_budget_min: dict[str, int]`, `settings.delays["candidate"] == 5.0`, `"candidate" in settings.robots_labels`.

- [ ] **Step 1: 기존 기본값 테스트를 새 스펙에 맞게 고치고 새 테스트를 추가한다**

`tests/test_config.py` 의 `test_defaults_match_spec` 를 아래로 바꾸고, 그 뒤에 세 테스트를 추가한다.

```python
def test_defaults_match_spec():
    s = Settings(out_root=Path("/x"), salt="s")
    assert (s.per_domain, s.max_domains, s.concurrency, s.page_timeout_ms, s.settle_ms, s.max_page_height) == (4, 300, 3, 20000, 1500, 15000)
    assert s.delays == {"gambling": 3.0, "embedded_banner": 3.0, "hard_negative": 5.0, "normal": 5.0, "candidate": 5.0}
    assert s.robots_labels == frozenset({"hard_negative", "normal", "candidate"}) and s.device == "Pixel 7"
    assert (s.recapture_days, s.skip_blocked_days) == (7, 7)
    assert (s.nightly_search_auto, s.nightly_max_candidates, s.nightly_candidate_pages, s.nightly_max_auto_communities) == (5, 40, 2, 5)
    assert (s.auto_keyword_pool, s.auto_keyword_add_per_day, s.auto_keyword_retire_streak) == (30, 5, 3)
    assert s.nightly_budget_min == {"search": 12, "community": 8, "explore": 25, "capture": 40}


def test_review_root_defaults_under_out_root():
    s = Settings(out_root=Path("/x"), salt="s")
    assert s.review_root == Path("/x/_review")
    assert CANDIDATE_LABEL == "candidate" and CANDIDATE_LABEL not in LABELS


def test_review_root_from_env_and_override(tmp_path):
    s = load_settings(out=str(tmp_path), env={"CRAWLER_SALT": "s", "CRAWLER_REVIEW": "/r/from/env"}, env_file=tmp_path / "none")
    assert s.review_root == Path("/r/from/env")
    s2 = load_settings(out=str(tmp_path), env={"CRAWLER_SALT": "s", "CRAWLER_REVIEW": "/r/from/env"}, env_file=tmp_path / "none",
                       review_root=Path("/r/cli"))
    assert s2.review_root == Path("/r/cli")


def test_default_out_moved_to_datasets():
    assert DEFAULT_OUT == Path("/Users/seongmin/datasets/gambling")
```

파일 맨 위 import 를 `from crawler.config import CANDIDATE_LABEL, DEFAULT_OUT, LABELS, Settings, load_settings, read_env_file` 로 바꾼다.

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'CANDIDATE_LABEL'`.

- [ ] **Step 3: config.py 구현**

`src/crawler/config.py` 전체를 아래로 바꾼다.

```python
"""실행 설정. 우선순위: CLI 인자 > 환경변수/.env > 기본값."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_OUT = Path("/Users/seongmin/datasets/gambling")
LABELS = ("gambling", "embedded_banner", "hard_negative", "normal")
CANDIDATE_LABEL = "candidate"   # 선캡처 전용 라벨. 데이터셋 라벨이 아니며 리뷰 루트에만 쓴다


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
    viewport_width: int = 412   # Playwright 기본 프로필(412×839, DPR 2.625)과 달리 스펙 값으로 고정
    viewport_height: int = 915
    dpr: int = 2
    refresh: bool = False   # 최근 창 안에 캡처한 홈도 다시 열어 내부 링크를 새로 모은다
    click_menus: bool = False   # 홈의 충전·입금·가입 메뉴(버튼·JS 링크)를 클릭해 결제 직전 화면을 추가 수집
    max_menu_clicks: int = 2    # 도메인당 클릭할 메뉴 수(내부 URL 메뉴는 클릭 대신 큐 앞에 넣으므로 제외)
    recapture_days: int = 7     # 이 일수 안에 찍은 화면은 유효한 것으로 보고 다시 찍지 않는다(야간 루프는 1)
    skip_blocked_days: int = 7  # 홈이 이 일수 안에 blocked_kr 였던 도메인은 통째로 건너뛴다
    review_root: Path | None = None   # 선캡처(candidate) 저장 루트. None 이면 out_root/_review
    nightly_search_auto: int = 5            # 밤당 돌릴 자동 키워드 수
    nightly_max_candidates: int = 40        # 밤당 선캡처할 새 후보 도메인 수
    nightly_candidate_pages: int = 2        # 후보 도메인당 페이지 수
    nightly_max_auto_communities: int = 5   # 밤당 커뮤니티 자동 등록 수
    auto_keyword_pool: int = 30             # 자동 키워드 풀 상한
    auto_keyword_add_per_day: int = 5       # 하루에 더할 자동 키워드 수
    auto_keyword_retire_streak: int = 3     # 후보 0 이 이만큼 연속이면 퇴역
    nightly_budget_min: dict[str, int] = field(default_factory=lambda: {"search": 12, "community": 8, "explore": 25, "capture": 40})
    delays: dict[str, float] = field(default_factory=lambda: {
        "gambling": 3.0, "embedded_banner": 3.0, "hard_negative": 5.0, "normal": 5.0, "candidate": 5.0})
    robots_labels: frozenset[str] = frozenset({"hard_negative", "normal", "candidate"})

    def __post_init__(self) -> None:
        self.out_root = Path(self.out_root)
        self.review_root = Path(self.review_root) if self.review_root is not None else self.out_root / "_review"


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
    if "review_root" not in clean and merged.get("CRAWLER_REVIEW"):
        clean["review_root"] = Path(merged["CRAWLER_REVIEW"])
    return Settings(out_root=root, salt=salt, **clean)
```

- [ ] **Step 4: `.env.example` 과 `.gitignore` 갱신**

`.env.example` 전체:

```
# 수집 결과 루트 (없으면 /Users/seongmin/datasets/gambling)
CRAWLER_OUT=/Users/seongmin/datasets/gambling
# 선캡처(후보 검토) 루트. 없으면 <CRAWLER_OUT>/_review
# CRAWLER_REVIEW=/Users/seongmin/datasets/gambling/_review
# 도메인 해시 솔트. 임의의 긴 문자열. 없으면 실행이 거부된다.
CRAWLER_SALT=change-me-to-a-long-random-string
```

`.gitignore` 의 `# 환경` 블록 아래에 추가:

```
# 야간 루프 산출물
out/
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS (52 + 3 = 55).

- [ ] **Step 6: 커밋**

```bash
git add src/crawler/config.py tests/test_config.py .env.example .gitignore
git commit -m "feat(crawler): settings for nightly loop — recapture window, review root, caps; default out moved to ~/datasets

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: seeds — CSV 행 갱신 헬퍼와 키워드 파일

**Files:**
- Modify: `src/crawler/seeds.py`
- Test: `tests/test_seeds.py`

**Interfaces:**
- Produces:
  - `read_rows(path: Path) -> list[dict[str, str]]` 원본 행(중복 포함), 없으면 `[]`
  - `write_rows(path: Path, rows: list[dict[str, str]]) -> None` HEADER 순서로 덮어쓰기
  - `update_notes(path: Path, notes: dict[str, str]) -> int` 등록 도메인 → note, 바뀐 행 수
  - `append_seed(path: Path, url: str, source: str, note: str = "", added_at: str | None = None) -> bool` 같은 등록 도메인이 있으면 False
  - `remove_domain(path: Path, domain: str) -> int` 지운 행 수
  - `update_source(path: Path, domain: str, source: str) -> bool`
  - `read_keywords(path: Path) -> list[str]` 주석·빈 줄 제외, 순서 유지, 중복 제거
  - `write_keywords(path: Path, keywords: list[str], header: str) -> None`
  - `all_seed_files(seeds_dir: Path) -> list[Path]` 라벨 4개 + community_lists + candidates

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_seeds.py` 끝에 추가

```python
from crawler.seeds import (
    all_seed_files, append_seed, read_keywords, read_rows, remove_domain, update_notes, update_source, write_keywords, write_rows,
)


CSV = ("url,source,added_at,note\n"
       "https://a.com/,search:토토,2026-10-01,unverified\n"
       "https://www.b.net/x,community:v.com,2026-10-02,unverified\n"
       "https://c.org/,manual,2026-10-03,→ gambling.csv (검토)\n")


def test_read_rows_keeps_raw_rows_and_write_rows_roundtrips(tmp_path):
    p = write(tmp_path / "c.csv", CSV)
    rows = read_rows(p)
    assert [r["url"] for r in rows] == ["https://a.com/", "https://www.b.net/x", "https://c.org/"]
    write_rows(p, rows)
    assert p.read_text(encoding="utf-8") == CSV
    assert read_rows(tmp_path / "missing.csv") == []


def test_update_notes_by_registrable_domain(tmp_path):
    p = write(tmp_path / "c.csv", CSV)
    assert update_notes(p, {"b.net": "review: 2026-10-20", "zzz.com": "ignored"}) == 1
    rows = read_rows(p)
    assert rows[1]["note"] == "review: 2026-10-20" and rows[0]["note"] == "unverified"
    assert p.read_text(encoding="utf-8").count("\r") == 0


def test_append_seed_dedups_domain_and_creates_file(tmp_path):
    p = tmp_path / "g.csv"
    assert append_seed(p, "https://new.com/", "review:2026-10-20", "nightly 승격", added_at="2026-10-20") is True
    assert append_seed(p, "https://www.new.com/other", "review:2026-10-20") is False
    assert p.read_text(encoding="utf-8") == "url,source,added_at,note\nhttps://new.com/,review:2026-10-20,2026-10-20,nightly 승격\n"


def test_remove_domain_and_update_source(tmp_path):
    p = write(tmp_path / "c.csv", CSV)
    assert update_source(p, "a.com", "review:2026-10-20") is True and update_source(p, "nope.com", "x") is False
    assert read_rows(p)[0]["source"] == "review:2026-10-20"
    assert remove_domain(p, "b.net") == 1 and remove_domain(p, "b.net") == 0
    assert [r["url"] for r in read_rows(p)] == ["https://a.com/", "https://c.org/"]


def test_read_write_keywords(tmp_path):
    p = write(tmp_path / "k.txt", "# 주석\n토토사이트\n\n토토사이트\n  카지노사이트 \n")
    assert read_keywords(p) == ["토토사이트", "카지노사이트"]
    write_keywords(p, ["a", "b"], header="# 자동")
    assert p.read_text(encoding="utf-8") == "# 자동\na\nb\n"
    assert read_keywords(tmp_path / "none.txt") == []


def test_all_seed_files_order(tmp_path):
    names = [p.name for p in all_seed_files(tmp_path)]
    assert names == ["gambling.csv", "embedded_banner.csv", "hard_negative.csv", "normal.csv", "community_lists.csv", "candidates.csv"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_seeds.py -q`
Expected: FAIL — ImportError (`all_seed_files` 등 없음).

- [ ] **Step 3: seeds.py 에 구현 추가** — 파일 끝에 덧붙인다 (`from .config import LABELS` 를 import 블록에 추가)

```python
def read_rows(path: Path) -> list[dict[str, str]]:
    """원본 행 그대로(중복 포함). 다시 써야 할 때 쓴다."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (row.get(k) or "").strip() for k in HEADER} for row in csv.DictReader(f)]


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        w.writerows([[r.get(k, "") for k in HEADER] for r in rows])


def update_notes(path: Path, notes: dict[str, str]) -> int:
    rows = read_rows(path)
    n = 0
    for r in rows:
        new = notes.get(registrable_domain(r["url"]))
        if new is not None and r["note"] != new:
            r["note"] = new
            n += 1
    if n:
        write_rows(path, rows)
    return n


def append_seed(path: Path, url: str, source: str, note: str = "", added_at: str | None = None) -> bool:
    path = Path(path)
    dom = registrable_domain(url)
    if dom in {registrable_domain(r["url"]) for r in read_rows(path)}:
        return False
    new_file = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new_file:
            w.writerow(HEADER)
        w.writerow([url, source, added_at or date.today().isoformat(), note])
    return True


def remove_domain(path: Path, domain: str) -> int:
    rows = read_rows(path)
    kept = [r for r in rows if registrable_domain(r["url"]) != domain]
    if len(kept) != len(rows):
        write_rows(path, kept)
    return len(rows) - len(kept)


def update_source(path: Path, domain: str, source: str) -> bool:
    rows = read_rows(path)
    hit = False
    for r in rows:
        if registrable_domain(r["url"]) == domain:
            r["source"] = source
            hit = True
    if hit:
        write_rows(path, rows)
    return hit


def read_keywords(path: Path) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        kw = line.strip()
        if kw and not kw.startswith("#") and kw not in out:
            out.append(kw)
    return out


def write_keywords(path: Path, keywords: list[str], header: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join([header + "\n"] + [k + "\n" for k in keywords]), encoding="utf-8")


def all_seed_files(seeds_dir: Path) -> list[Path]:
    seeds_dir = Path(seeds_dir)
    return [seeds_dir / f"{lab}.csv" for lab in LABELS] + [seeds_dir / "community_lists.csv", seeds_dir / "candidates.csv"]
```

`__main__.py` 의 `ALL_SEED_FILES = [...]` 줄을 `ALL_SEED_FILES = all_seed_files(SEEDS_DIR)` 로 바꾸고 import 에 `all_seed_files` 를 추가한다.

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/seeds.py src/crawler/__main__.py tests/test_seeds.py
git commit -m "feat(crawler): seed csv row helpers (notes, append, remove, source) and keyword files

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: store — 재캡처 창, 최근 차단 판정, 도메인 행 제거·편입

**Files:**
- Modify: `src/crawler/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `Store.ok_count(label, domain, days: int | None = None, now=None) -> int` — `days` 가 있으면 그 창 안의 ok 만 센다
  - `Store.rows_for(label, domain) -> list[dict]`
  - `Store.page_index(meta) -> int` (정적, `id` 끝의 idx, 없으면 -1)
  - `Store.blocked_recently(label, domain, days=7, now=None) -> bool` — 가장 최근 홈(idx 0) 행이 `blocked_kr` 이고 창 안이면 True
  - `Store.rewrite_index() -> None`
  - `Store.remove_domain(label, domain, delete_files=True) -> int`
  - `Store.adopt_domain(src_dir: Path, rows: list[dict], label: str) -> list[dict]` — 폴더 이동 + label·`full_path`·`banners[].path` 재기록 + 색인 추가

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_store.py` 끝에 추가

```python
import json


def meta_idx(label, domain, status, idx, at, store, phash="0" * 64):
    h = store.hash_of(domain)
    stem = f"{ts_label(at)}_{idx}"
    ok = status == "ok"
    return {"id": f"{h}_{stem}", "label": label, "domain": domain, "domain_hash": h, "status": status,
            "url": f"https://{domain}/{idx}", "url_norm": f"https://{domain}/{idx}", "phash": phash, "captured_at": at.isoformat(),
            "full_path": f"{label}/{h}/{stem}_full.png" if ok else None,
            "banners": [{"path": f"{label}/{h}/{stem}_b0.png", "external": True}] if ok else []}


def test_ok_count_window_and_rows_for(tmp_path):
    s = Store(tmp_path, "salt")
    old = datetime(2026, 10, 1, tzinfo=KST); recent = datetime(2026, 10, 19, 23, 0, tzinfo=KST)
    s.record(meta_idx("gambling", "a.com", "ok", 0, old, s)); s.record(meta_idx("gambling", "a.com", "ok", 1, recent, s))
    now = datetime(2026, 10, 20, 4, 30, tzinfo=KST)
    assert s.ok_count("gambling", "a.com") == 2
    assert s.ok_count("gambling", "a.com", days=7, now=now) == 1
    assert s.ok_count("gambling", "a.com", days=0, now=now) == 0
    assert len(s.rows_for("gambling", "a.com")) == 2 and s.rows_for("normal", "a.com") == []
    assert Store.page_index(s.rows_for("gambling", "a.com")[1]) == 1 and Store.page_index({"id": "x_20260930T200000"}) == -1


def test_blocked_recently_uses_latest_home_row(tmp_path):
    s = Store(tmp_path, "salt")
    now = datetime(2026, 10, 20, 4, 30, tzinfo=KST)
    s.record(meta_idx("gambling", "b.com", "blocked_kr", 0, datetime(2026, 10, 19, tzinfo=KST), s))
    assert s.blocked_recently("gambling", "b.com", days=7, now=now)
    assert not s.blocked_recently("gambling", "b.com", days=0, now=now)
    assert not s.blocked_recently("normal", "b.com", days=7, now=now)
    s.record(meta_idx("gambling", "b.com", "ok", 0, datetime(2026, 10, 19, 12, tzinfo=KST), s))   # 더 최근 홈이 ok
    assert not s.blocked_recently("gambling", "b.com", days=7, now=now)
    s.record(meta_idx("gambling", "c.com", "blocked_kr", 1, datetime(2026, 10, 19, tzinfo=KST), s))   # 홈이 아닌 행은 무시
    assert not s.blocked_recently("gambling", "c.com", days=7, now=now)


def test_remove_domain_rewrites_index_and_deletes_dir(tmp_path):
    s = Store(tmp_path, "salt")
    at = datetime(2026, 10, 19, tzinfo=KST)
    s.record(meta_idx("gambling", "a.com", "ok", 0, at, s)); s.record(meta_idx("gambling", "z.com", "ok", 0, at, s))
    (s.domain_dir("gambling", "a.com") / "x_full.png").write_bytes(b"png")
    assert s.remove_domain("gambling", "a.com") == 1
    assert not s.domain_dir("gambling", "a.com").exists()
    assert [m["domain"] for m in Store(tmp_path, "salt").load_index()] == ["z.com"]
    assert s.remove_domain("gambling", "a.com") == 0


def test_adopt_domain_moves_files_and_relabels_rows(tmp_path):
    review = Store(tmp_path / "_review", "salt"); main = Store(tmp_path, "salt")
    at = datetime(2026, 10, 19, tzinfo=KST)
    for idx in (0, 1):
        review.record(meta_idx("candidate", "a.com", "ok", idx, at, review))
    src = review.domain_dir("candidate", "a.com")
    for name in (f"{ts_label(at)}_0_full.png", f"{ts_label(at)}_0_b0.png"):
        (src / name).write_bytes(b"png")
    new_rows = main.adopt_domain(src, review.rows_for("candidate", "a.com"), "gambling")
    dest = main.domain_dir("gambling", "a.com")
    assert not src.exists() and (dest / f"{ts_label(at)}_0_full.png").exists()
    assert [r["label"] for r in new_rows] == ["gambling", "gambling"]
    assert new_rows[0]["full_path"] == f"gambling/{main.hash_of('a.com')}/{ts_label(at)}_0_full.png"
    assert new_rows[0]["banners"][0]["path"].startswith(f"gambling/{main.hash_of('a.com')}/")
    meta_lines = [json.loads(l) for l in (dest / "meta.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [m["label"] for m in meta_lines] == ["gambling", "gambling"]
    assert main.ok_count("gambling", "a.com") == 2 and Store(tmp_path, "salt").ok_count("gambling", "a.com") == 2
    assert review.remove_domain("candidate", "a.com", delete_files=False) == 2 and review.rows_for("candidate", "a.com") == []
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_store.py -q`
Expected: FAIL — `TypeError: ok_count() got an unexpected keyword argument 'days'` 등.

- [ ] **Step 3: store.py 구현** — import 에 `import shutil` 추가, `ok_count` 를 바꾸고 나머지 메서드를 클래스 끝에 추가

```python
    def ok_count(self, label: str, domain: str, days: int | None = None, now: datetime | None = None) -> int:
        """ok 행 수. days 가 있으면 그 일수 안에 찍은 것만 센다(재캡처 창)."""
        now = now or now_kst()
        n = 0
        for m in self._index:
            if m["label"] != label or m["domain"] != domain or m["status"] != "ok":
                continue
            if days is None or now - datetime.fromisoformat(m["captured_at"]) <= timedelta(days=days):
                n += 1
        return n

    def rows_for(self, label: str, domain: str) -> list[dict]:
        return [m for m in self._index if m["label"] == label and m["domain"] == domain]

    @staticmethod
    def page_index(meta: dict) -> int:
        """id `<해시>_<시각>_<idx>` 의 idx. 홈은 0. 형식이 다르면 -1."""
        try:
            return int(str(meta.get("id", "")).rsplit("_", 1)[1])
        except (IndexError, ValueError):
            return -1

    def blocked_recently(self, label: str, domain: str, days: int = 7, now: datetime | None = None) -> bool:
        """가장 최근 홈(idx 0) 행이 blocked_kr 이고 days 안이면 참. 같은 망에서 다시 두드려도 결과가 같기 때문에 건너뛴다."""
        now = now or now_kst()
        homes = [m for m in self.rows_for(label, domain) if self.page_index(m) == 0]
        if not homes:
            return False
        last = max(homes, key=lambda m: m["captured_at"])
        return last["status"] == "blocked_kr" and now - datetime.fromisoformat(last["captured_at"]) <= timedelta(days=days)

    def rewrite_index(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("w", encoding="utf-8") as f:
            for m in self._index:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def remove_domain(self, label: str, domain: str, delete_files: bool = True) -> int:
        """색인에서 (label, domain) 행을 지우고(파일 다시 씀) 폴더를 삭제한다. 지운 행 수."""
        before = len(self._index)
        self._index = [m for m in self._index if not (m["label"] == label and m["domain"] == domain)]
        removed = before - len(self._index)
        if removed:
            self.rewrite_index()
        d = self.domain_dir(label, domain)
        if delete_files and d.exists():
            shutil.rmtree(d)
        return removed

    def adopt_domain(self, src_dir: Path, rows: list[dict], label: str) -> list[dict]:
        """다른 루트의 도메인 폴더와 행들을 이 루트의 label 아래로 들인다.
        폴더를 옮기고, 행의 label·full_path·banners[].path 접두를 고쳐 meta.jsonl·index.jsonl 에 기록한다. 새 행 목록을 돌려준다."""
        if not rows:
            return []
        domain = rows[0]["domain"]
        dest = self.domain_dir(label, domain)
        old_prefix = f"{rows[0]['label']}/{rows[0]['domain_hash']}/"
        new_prefix = f"{label}/{self.hash_of(domain)}/"
        src_dir = Path(src_dir)
        dest_existed = dest.exists()
        if src_dir.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest_existed:
                for p in src_dir.iterdir():
                    if p.name != "meta.jsonl" and not (dest / p.name).exists():
                        shutil.move(str(p), str(dest / p.name))
                shutil.rmtree(src_dir)
            else:
                shutil.move(str(src_dir), str(dest))
                (dest / "meta.jsonl").unlink(missing_ok=True)   # 옛 라벨 행은 아래서 새로 쓴다

        def fix(path: str | None) -> str | None:
            if path and path.startswith(old_prefix):
                return new_prefix + path[len(old_prefix):]
            return path

        out: list[dict] = []
        for m in rows:
            n = json.loads(json.dumps(m, ensure_ascii=False))
            n["label"] = label
            n["domain_hash"] = self.hash_of(domain)
            n["full_path"] = fix(n.get("full_path"))
            n["banners"] = [{**b, "path": fix(b.get("path"))} for b in (n.get("banners") or [])]
            self.record(n)
            out.append(n)
        return out
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/store.py tests/test_store.py
git commit -m "feat(crawler): store — recapture window, recently-blocked check, remove/adopt domain

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: capture — 본문 발췌·외부 도메인 기록, 재캡처 창, 차단 도메인 건너뛰기, 외부 Store

**Files:**
- Modify: `src/crawler/capture.py`
- Test: `tests/test_capture_integration.py`, `tests/test_capture.py`

**Interfaces:**
- Consumes: `Store.ok_count(days=)`, `Store.blocked_recently`, `Settings.recapture_days`, `Settings.skip_blocked_days`, `seeds.is_platform`
- Produces:
  - meta 필드 `text_excerpt: str | None`(공백 정리한 본문 앞 300자, ok 행에만), `ext_domains: list[str]`(홈의 외부 등록 도메인 ≤ 20, 플랫폼 제외, 홈이 아닌 행은 `[]`)
  - `external_domains(hrefs: list[str], page_domain: str, limit: int = 20) -> list[str]` (순수 함수)
  - `run_capture(settings, seeds, *, label, emit_candidates=False, candidates_path=None, known_domains=frozenset(), store: Store | None = None) -> dict` — 요약에 `skipped_blocked` 키 추가

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_capture.py` 끝에 추가:

```python
from crawler.capture import external_domains


def test_external_domains_excludes_same_domain_platform_and_dups_with_limit():
    hrefs = ["https://site.com/a", "https://www.toto-partner.com/j", "https://naver.com/x", "https://toto-partner.com/k",
             "javascript:void(0)", "https://elsewhere.net/", "mailto:a@b.c"] + [f"https://d{i}.com/" for i in range(30)]
    got = external_domains(hrefs, "site.com")
    assert got[:2] == ["toto-partner.com", "elsewhere.net"] and len(got) == 20
```

`tests/test_capture_integration.py`: `fast_settings` 의 `delays` 에 `"candidate": 0.0` 을 추가하고(`delays={"gambling": 0.0, "embedded_banner": 0.0, "hard_negative": 0.0, "normal": 0.0, "candidate": 0.0}`), import 에 `from crawler.store import Store` 를 더한 뒤 끝에 추가:

```python
def index_rows(root):
    return [json.loads(l) for l in (root / "index.jsonl").read_text(encoding="utf-8").splitlines()]


async def test_meta_has_text_excerpt_and_external_domains(site, tmp_path):
    settings = fast_settings(tmp_path)
    await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-10-20")], label="gambling")
    home, charge = index_rows(settings.out_root)
    assert "첫 충전 100% 보너스" in home["text_excerpt"] and len(home["text_excerpt"]) <= 300
    assert home["ext_domains"] == ["toto-partner.com", "elsewhere.net"]
    assert charge["ext_domains"] == [] and charge["text_excerpt"].startswith("충전 신청")


async def test_recapture_window_zero_reshoots_and_dedups(site, tmp_path):
    settings = fast_settings(tmp_path)
    seed = [Seed(url=site + "/", source="test", added_at="2026-10-20")]
    first = await run_capture(settings, seed, label="gambling")
    settings.recapture_days = 0
    second = await run_capture(settings, seed, label="gambling")
    assert first["ok"] == 2
    assert second["skipped_domains"] == 0 and second["ok"] == 0 and second["duplicate"] == 2
    assert len([p for p in (settings.out_root / "gambling").rglob("*_full.png")]) == 2   # 중복 파일은 남기지 않는다


async def test_recently_blocked_domain_is_skipped_until_window_passes(site, tmp_path):
    settings = fast_settings(tmp_path)
    seed = [Seed(url=site + "/warning.html", source="test", added_at="2026-10-20")]
    first = await run_capture(settings, seed, label="gambling")
    settings.recapture_days = 0
    second = await run_capture(settings, seed, label="gambling")
    assert first["blocked_kr"] == 1 and second["skipped_blocked"] == 1 and second["blocked_kr"] == 0 and second["domains"] == 1
    settings.skip_blocked_days = 0
    third = await run_capture(settings, seed, label="gambling")
    assert third["blocked_kr"] == 1 and third["skipped_blocked"] == 0


async def test_run_capture_writes_to_external_store(site, tmp_path):
    settings = fast_settings(tmp_path)
    review = Store(tmp_path / "_review", settings.salt)
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-10-20")], label="candidate", store=review)
    assert summary["ok"] == 2 and not (settings.out_root / "index.jsonl").exists()
    rows = index_rows(tmp_path / "_review")
    assert rows[0]["label"] == "candidate" and rows[0]["full_path"].startswith("candidate/")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_capture.py tests/test_capture_integration.py -q`
Expected: FAIL — `external_domains` ImportError, `KeyError: 'text_excerpt'`, `run_capture() got an unexpected keyword argument 'store'`.

- [ ] **Step 3: capture.py 수정**

(a) import 에 `from .seeds import Seed, append_candidates, is_platform` (기존 줄 교체).

(b) `pick_internal_links` 아래에 추가:

```python
def external_domains(hrefs: list[str], page_domain: str, limit: int = 20) -> list[str]:
    """페이지의 외부 링크 등록 도메인(플랫폼 제외, 순서 유지, 중복 제거). 커뮤니티 판정과 검토 화면에 쓴다."""
    out: list[str] = []
    for h in hrefs:
        if not h.startswith(("http://", "https://")):
            continue
        d = registrable_domain(h)
        if not d or d == page_domain or is_platform(d) or d in out:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out
```

(c) `_empty_meta` 의 dict 끝에 `"text_excerpt": None, "ext_domains": []` 를 추가한다(`"error": None` 앞).

(d) `capture_page` 에서 `meta["title"] = await page.title()` 바로 뒤에 `meta["text_excerpt"] = " ".join(body_text.split())[:300]` 를 넣고, `if idx == 0:` 블록을 아래로 바꾼다:

```python
        if idx == 0:
            hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            links = pick_internal_links(hrefs, domain, page.url, settings.per_domain - 1)
            meta["ext_domains"] = external_domains(hrefs, domain)
```

(e) `_menu_phase` 의 `if store.ok_count(label, domain) >= settings.per_domain:` 를 `if store.ok_count(label, domain, days=settings.recapture_days) >= settings.per_domain:` 로.

(f) `capture_domain`: `stats = {"menu_clicks": 0, "menu_captures": 0}` 를 `stats = {"menu_clicks": 0, "menu_captures": 0, "skipped_blocked": 0}` 로 바꾸고, `page = await context.new_page()` 앞에 넣는다:

```python
    if store.blocked_recently(label, domain, settings.skip_blocked_days):
        stats["skipped_blocked"] = 1
        return metas, candidates, stats
```

while 조건을 `while queue and store.ok_count(label, domain, days=settings.recapture_days) < settings.per_domain and idx < settings.per_domain + 2:` 로, `if store.seen_recently(url) and ...` 를 `if store.seen_recently(url, days=settings.recapture_days) and not (settings.refresh and idx == 0):` 로 바꾼다.

(g) `run_capture`:

```python
async def run_capture(settings: Settings, seeds: list[Seed], *, label: str, emit_candidates: bool = False,
                      candidates_path: Path | None = None, known_domains: frozenset[str] = frozenset(),
                      store: Store | None = None) -> dict:
    store = store or Store(settings.out_root, settings.salt)
    summary: dict = {s: 0 for s in STATUSES}
    summary.update({"skipped_domains": 0, "skipped_blocked": 0, "domains": 0, "candidates_added": 0, "menu_clicks": 0, "menu_captures": 0})
    todo: list[Seed] = []
    for seed in seeds:
        if store.ok_count(label, registrable_domain(seed.url), days=settings.recapture_days) >= settings.per_domain:
            summary["skipped_domains"] += 1
            continue
```
(이하 기존과 같다.)

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/capture.py tests/test_capture.py tests/test_capture_integration.py
git commit -m "feat(crawler): record text excerpt and external domains; recapture window; skip recently blocked domains

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: keywords — 제목에서 용어 추출, 자동 키워드 회전·수확·퇴역

**Files:**
- Create: `src/crawler/keywords.py`
- Test: `tests/test_keywords.py`

**Interfaces:**
- Produces:
  - `SUFFIXES`, `AUTO_HEADER` (keywords_auto.txt 첫 줄)
  - `extract_terms(titles: Iterable[str], known: set[str], min_len=3, max_len=12) -> list[tuple[str, int]]` 등장 수 내림차순
  - `load_state(path) -> dict` / `save_state(path, state) -> None` — `{"keywords": {kw: {origin, runs, added_total, zero_streak, last_run, retired}}, "bot_check_date": str | None}`
  - `pick_auto_keywords(state, auto_keywords: list[str], n: int) -> list[str]` — 안 돌린 것 → 가장 오래된 것 순
  - `record_run(state, keyword, added: int, today: str, origin: str) -> None`
  - `expand(state, auto_keywords, terms, *, add_per_day, pool, retire_streak) -> tuple[list[str], list[str], list[str]]` — (새 목록, 추가, 퇴역)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_keywords.py`

```python
from crawler.keywords import expand, extract_terms, load_state, pick_auto_keywords, record_run, save_state


def test_extract_terms_counts_suffix_terms_once_per_title():
    titles = ["토토사이트 추천 | 안전놀이터 먹튀검증 메이저사이트 순위",
              "안전놀이터 모음 - 안전놀이터 추천 2026",
              "Best Casino Online",
              "사이트 토토 1xbet 홀덤사이트"]
    got = extract_terms(titles, known={"토토사이트"})
    assert got[0] == ("안전놀이터", 2)                      # 제목당 한 번만 센다
    terms = dict(got)
    assert "토토사이트" not in terms and "사이트" not in terms and "토토" not in terms   # 알려진 것·접미사 자체·2글자 제외
    assert terms["먹튀검증"] == 1 and terms["메이저사이트"] == 1 and terms["홀덤사이트"] == 1
    assert "추천 안전놀이터" in terms                        # 앞 토큰이 한글이면 2토큰 용어도 후보
    assert "1xbet 홀덤사이트" not in terms                   # 앞 토큰에 숫자
    assert all(3 <= len(t) <= 12 for t in terms)
    assert extract_terms([], known=set()) == []


def test_state_roundtrip_and_rotation(tmp_path):
    p = tmp_path / "state.json"
    state = load_state(p)
    assert state == {"keywords": {}, "bot_check_date": None}
    record_run(state, "a", added=2, today="2026-10-18", origin="auto")
    record_run(state, "b", added=0, today="2026-10-19", origin="auto")
    record_run(state, "b", added=0, today="2026-10-20", origin="auto")
    assert state["keywords"]["b"] == {"origin": "auto", "runs": 2, "added_total": 0, "zero_streak": 2, "last_run": "2026-10-20", "retired": False}
    assert state["keywords"]["a"]["added_total"] == 2 and state["keywords"]["a"]["zero_streak"] == 0
    save_state(p, state)
    assert load_state(p) == state
    assert pick_auto_keywords(state, ["a", "b", "c", "d"], 2) == ["c", "d"]   # 한 번도 안 돌린 것 먼저
    assert pick_auto_keywords(state, ["a", "b"], 1) == ["a"]                 # 그다음 가장 오래된 것


def test_expand_retires_and_adds_within_caps():
    state = {"keywords": {
        "old": {"origin": "auto", "runs": 3, "added_total": 0, "zero_streak": 3, "last_run": "2026-10-19", "retired": False},
        "gone": {"origin": "auto", "runs": 1, "added_total": 0, "zero_streak": 0, "last_run": None, "retired": True}},
        "bot_check_date": None}
    auto = ["old", "keep"]
    terms = [("gone", 5), ("새사이트", 4), ("keep", 3), ("다른놀이터", 2), ("셋째카지노", 1)]
    new, added, retired = expand(state, auto, terms, add_per_day=2, pool=30, retire_streak=3)
    assert retired == ["old"] and state["keywords"]["old"]["retired"] is True
    assert added == ["새사이트", "다른놀이터"] and new == ["keep", "새사이트", "다른놀이터"]   # 퇴역·기존·이미 퇴역한 용어는 건너뜀
    assert state["keywords"]["새사이트"] == {"origin": "auto", "runs": 0, "added_total": 0, "zero_streak": 0, "last_run": None, "retired": False}
    new2, added2, retired2 = expand(state, new, [("넷째사이트", 1)], add_per_day=5, pool=3, retire_streak=3)
    assert added2 == [] and retired2 == [] and new2 == new   # 풀 상한
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_keywords.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawler.keywords'`.

- [ ] **Step 3: keywords.py 작성**

```python
"""검색 키워드 자동 확장: 제목에서 용어 추출, 자동 키워드 회전·수확 기록·퇴역. 상태는 seeds/explore_state.json."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

SUFFIXES = ("사이트", "놀이터", "검증", "카지노", "토토", "슬롯", "바카라", "파워볼", "홀덤", "릴게임")
AUTO_HEADER = "# 자동 키워드 — nightly 가 관리. 손으로 고치려면 keywords.txt 를 쓸 것"
_SPLIT = re.compile(r"[\s|\-–—·,.:;!?()\[\]【】\"'/\\<>]+")
_HANGUL = re.compile(r"[가-힣]")


def _tokens(title: str) -> list[str]:
    return [t for t in _SPLIT.split(title or "") if t]


def _acceptable(term: str, known: set[str], min_len: int, max_len: int) -> bool:
    return (min_len <= len(term) <= max_len and term.endswith(SUFFIXES) and term not in SUFFIXES
            and bool(_HANGUL.search(term)) and term not in known)


def extract_terms(titles: Iterable[str], known: set[str], min_len: int = 3, max_len: int = 12) -> list[tuple[str, int]]:
    """제목들에서 접미사(사이트·놀이터·…)로 끝나는 1~2 토큰 용어를 뽑아 (용어, 등장 제목 수) 로 돌려준다.
    등장 수 내림차순, 같으면 가나다. 2토큰 용어는 앞 토큰이 한글이고 숫자가 없을 때만."""
    counts: Counter[str] = Counter()
    for title in titles:
        toks = _tokens(title)
        seen: set[str] = set()
        for i, tok in enumerate(toks):
            cands = [tok]
            if i > 0 and _HANGUL.search(toks[i - 1]) and not any(ch.isdigit() for ch in toks[i - 1]):
                cands.append(f"{toks[i - 1]} {tok}")
            for c in cands:
                if c not in seen and _acceptable(c, known, min_len, max_len):
                    seen.add(c)
                    counts[c] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _blank(origin: str) -> dict:
    return {"origin": origin, "runs": 0, "added_total": 0, "zero_streak": 0, "last_run": None, "retired": False}


def load_state(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"keywords": {}, "bot_check_date": None}
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("keywords", {})
    state.setdefault("bot_check_date", None)
    return state


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def pick_auto_keywords(state: dict, auto_keywords: list[str], n: int) -> list[str]:
    """회전: last_run 이 없는 것부터, 그다음 가장 오래된 것부터 n개."""
    def key(kw: str) -> tuple[str, int]:
        return (state["keywords"].get(kw, {}).get("last_run") or "", auto_keywords.index(kw))
    return sorted(auto_keywords, key=key)[:n]


def record_run(state: dict, keyword: str, added: int, today: str, origin: str) -> None:
    info = state["keywords"].setdefault(keyword, _blank(origin))
    info["runs"] += 1
    info["added_total"] += added
    info["zero_streak"] = 0 if added > 0 else info.get("zero_streak", 0) + 1
    info["last_run"] = today


def expand(state: dict, auto_keywords: list[str], terms: list[tuple[str, int]], *,
           add_per_day: int, pool: int, retire_streak: int) -> tuple[list[str], list[str], list[str]]:
    """퇴역(zero_streak ≥ retire_streak) 뒤 새 용어를 더한다. (새 자동 키워드 목록, 추가된 것, 퇴역한 것)."""
    retired = [kw for kw in auto_keywords if state["keywords"].get(kw, {}).get("zero_streak", 0) >= retire_streak]
    for kw in retired:
        state["keywords"][kw]["retired"] = True
    kept = [kw for kw in auto_keywords if kw not in retired]
    retired_all = {kw for kw, info in state["keywords"].items() if info.get("retired")}
    added: list[str] = []
    for term, _n in terms:
        if len(kept) + len(added) >= pool or len(added) >= add_per_day:
            break
        if term in kept or term in retired_all or term in added:
            continue
        added.append(term)
        state["keywords"][term] = _blank("auto")
    return kept + added, added, retired
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_keywords.py -q`
Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/keywords.py tests/test_keywords.py
git commit -m "feat(crawler): keyword expansion — term extraction, rotation state, retirement

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: review — 신호·추천 규칙과 review.csv

**Files:**
- Create: `src/crawler/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `Store.page_index`, `config.LABELS`
- Produces:
  - `VERDICTS = LABELS + ("community", "exclude", "blocked", "")`, `REVIEW_HEADER`
  - `@dataclass ReviewRow(domain, url, title, status, signals: list[str], suggested, verdict, note, review_dir)`
  - `signals(domain: str, rows: list[dict]) -> list[str]` (순서: ref_param, tld_gambling, idn, numeric, deposit_page, menu_terms, many_ext, verify_terms, 홈 상태)
  - `suggest(sig: list[str]) -> str`, `looks_like_community(sig) -> bool`
  - `build_row(domain, url, rows, review_dir) -> ReviewRow`
  - `write_review_csv(path, rows) -> None`, `read_review_csv(path) -> list[ReviewRow]`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_review.py`

```python
from crawler.review import REVIEW_HEADER, VERDICTS, ReviewRow, build_row, looks_like_community, read_review_csv, signals, suggest, write_review_csv


def row(idx, **kw):
    base = {"id": f"h_20261020T043000_{idx}", "status": "ok", "url": f"https://site.com/{idx}", "final_url": None, "title": "",
            "text_excerpt": "", "ext_domains": [], "page_kind": "home" if idx == 0 else "other", "captured_at": "2026-10-20T04:30:00+09:00"}
    base.update(kw)
    return base


def test_signals_table():
    assert signals("x.bet", [row(0, url="https://x.bet/?code=abc")]) == ["ref_param", "tld_gambling"]
    assert signals("y.com", [row(0, final_url="https://y.com/?Ref=7")]) == ["ref_param"]
    assert "idn" in signals("xn--oy2b17xfhh.com", [row(0)])
    assert "numeric" in signals("gdct18110.com", [row(0)]) and "numeric" not in signals("six-16.com", [row(0)])
    s = signals("op.com", [row(0, text_excerpt="실시간 배팅 첫 충전 보너스", ext_domains=["a.com", "b.com"]), row(1, page_kind="deposit")])
    assert s == ["deposit_page", "menu_terms"]
    s = signals("verify.net", [row(0, title="먹튀검증 커뮤니티", ext_domains=[f"d{i}.com" for i in range(8)])])
    assert s == ["many_ext", "verify_terms"]
    assert signals("b.com", [row(0, status="blocked_kr")]) == ["blocked_kr"]
    assert signals("plain.com", [row(0, text_excerpt="충전")]) == []   # 메뉴 용어 1종은 부족
    assert signals("none.com", []) == []


def test_suggest_priority_and_community():
    assert suggest(["blocked_kr", "deposit_page"]) == "blocked"
    assert suggest(["many_ext", "verify_terms", "menu_terms"]) == "community"
    assert suggest(["deposit_page"]) == "gambling" and suggest(["menu_terms", "many_ext"]) == ""
    assert suggest(["ref_param", "numeric"]) == "gambling" and suggest(["numeric"]) == ""
    assert suggest([]) == ""
    assert looks_like_community(["many_ext", "verify_terms"]) and not looks_like_community(["many_ext"])


def test_build_row_and_csv_roundtrip(tmp_path):
    rows = [row(0, title='테스트, "도박" 사이트', text_excerpt="충전 입금"), row(1, page_kind="deposit")]
    r = build_row("site.com", "https://site.com/", rows, "/x/_review/candidate/h")
    assert r.title.startswith("테스트") and r.status == "ok" and r.signals == ["deposit_page", "menu_terms"] and r.suggested == "gambling"
    assert r.verdict == "" and r.review_dir == "/x/_review/candidate/h"
    p = tmp_path / "review.csv"
    write_review_csv(p, [r, ReviewRow(domain="b.com", url="https://b.com/", title="", status="blocked_kr", signals=["blocked_kr"], suggested="blocked")])
    back = read_review_csv(p)
    assert back[0] == r and back[1].signals == ["blocked_kr"] and back[1].verdict == "" and back[1].suggested == "blocked"
    assert p.read_text(encoding="utf-8").splitlines()[0] == ",".join(REVIEW_HEADER)
    assert VERDICTS == ("gambling", "embedded_banner", "hard_negative", "normal", "community", "exclude", "blocked", "")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_review.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawler.review'`.

- [ ] **Step 3: review.py 작성**

```python
"""후보 검토: 신호·추천 규칙(순수 함수)과 review.csv 입출력. 추천값은 사람의 검토를 돕는 힌트일 뿐 라벨이 아니다."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .config import LABELS
from .store import Store

REF_KEYS = frozenset({"code", "ref", "aff", "partner", "invite", "recommend", "rec", "추천"})
GAMBLING_TLDS = (".bet", ".casino", ".poker", ".vip", ".win")
MENU_TERMS = ("충전", "입금", "출금", "환전", "가입", "배팅", "베팅", "카지노", "슬롯", "바카라", "파워볼")
VERIFY_TERMS = ("먹튀", "검증", "보증업체", "보증", "커뮤니티")
MANY_EXT_MIN = 8
HOME_STATUS_SIGNALS = ("blocked_kr", "challenge", "error")
VERDICTS = LABELS + ("community", "exclude", "blocked", "")
REVIEW_HEADER = ["domain", "url", "title", "status", "signals", "suggested", "verdict", "note", "review_dir"]
_DIGITS3 = re.compile(r"\d{3}")


@dataclass
class ReviewRow:
    domain: str
    url: str
    title: str
    status: str
    signals: list[str] = field(default_factory=list)
    suggested: str = ""
    verdict: str = ""
    note: str = ""
    review_dir: str = ""


def _has_ref_param(url: str | None) -> bool:
    if not url:
        return False
    return any(k.lower() in REF_KEYS for k, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True))


def home_row(rows: list[dict]) -> dict | None:
    """가장 최근 홈(idx 0) 행. 홈이 없으면 첫 행."""
    homes = [m for m in rows if Store.page_index(m) == 0]
    if homes:
        return max(homes, key=lambda m: m.get("captured_at") or "")
    return rows[0] if rows else None


def signals(domain: str, rows: list[dict]) -> list[str]:
    sig: list[str] = []
    home = home_row(rows)
    urls = [u for m in rows for u in (m.get("url"), m.get("final_url")) if u]
    if any(_has_ref_param(u) for u in urls):
        sig.append("ref_param")
    if domain.endswith(GAMBLING_TLDS):
        sig.append("tld_gambling")
    if "xn--" in domain:
        sig.append("idn")
    if any(_DIGITS3.search(label) for label in domain.split(".")):
        sig.append("numeric")
    if any(m.get("page_kind") in ("deposit", "register", "login") for m in rows):
        sig.append("deposit_page")
    texts = " ".join(f"{m.get('title') or ''} {m.get('text_excerpt') or ''}" for m in rows)
    if sum(1 for t in MENU_TERMS if t in texts) >= 2:
        sig.append("menu_terms")
    if home and len(home.get("ext_domains") or []) >= MANY_EXT_MIN:
        sig.append("many_ext")
    if any(t in texts for t in VERIFY_TERMS):
        sig.append("verify_terms")
    if home and home.get("status") in HOME_STATUS_SIGNALS:
        sig.append(home["status"])
    return sig


def looks_like_community(sig: list[str]) -> bool:
    return {"many_ext", "verify_terms"} <= set(sig)


def suggest(sig: list[str]) -> str:
    s = set(sig)
    if "blocked_kr" in s:
        return "blocked"
    if looks_like_community(sig):
        return "community"
    if ("deposit_page" in s or "menu_terms" in s) and "many_ext" not in s:
        return "gambling"
    if len(s & {"ref_param", "tld_gambling", "idn", "numeric"}) >= 2:
        return "gambling"
    return ""


def build_row(domain: str, url: str, rows: list[dict], review_dir: str) -> ReviewRow:
    home = home_row(rows) or {}
    sig = signals(domain, rows)
    return ReviewRow(domain=domain, url=url, title=home.get("title") or "", status=home.get("status") or "",
                     signals=sig, suggested=suggest(sig), review_dir=review_dir)


def write_review_csv(path: Path, rows: list[ReviewRow]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(REVIEW_HEADER)
        for r in rows:
            w.writerow([r.domain, r.url, r.title, r.status, "|".join(r.signals), r.suggested, r.verdict, r.note, r.review_dir])


def read_review_csv(path: Path) -> list[ReviewRow]:
    out: list[ReviewRow] = []
    with Path(path).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            g = {k: (row.get(k) or "").strip() for k in REVIEW_HEADER}
            out.append(ReviewRow(domain=g["domain"], url=g["url"], title=g["title"], status=g["status"],
                                 signals=[s for s in g["signals"].split("|") if s], suggested=g["suggested"],
                                 verdict=g["verdict"], note=g["note"], review_dir=g["review_dir"]))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_review.py -q`
Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/review.py tests/test_review.py
git commit -m "feat(crawler): review signals, suggestion rules and review.csv

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: discover — 키워드 목록 입력, 키워드별 수확, 봇 확인 조기 종료

**Files:**
- Modify: `src/crawler/discover.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: `seeds.read_keywords`
- Produces:
  - `class SearchTally(stop_after: int)` — `.add(keyword, links: int, added: int)`, `.links: dict[str,int]`, `.added: dict[str,int]`, `.zero_streak: int`, `.bot_check: bool`, `.total_added: int`
  - `discover_search_keywords(settings, keywords: list[str], out_csv: Path, known_domains: set[str], per_keyword: int = 20, stop_after_zero: int | None = 2) -> SearchTally`
  - 기존 `discover_search(settings, keywords_path, out_csv, known_domains, per_keyword=20) -> int` 는 유지(파일을 읽어 위 함수를 조기 종료 없이 호출)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_discover.py` 끝에 추가

```python
from crawler.discover import SearchTally


def test_search_tally_flags_bot_check_after_consecutive_zero_results():
    t = SearchTally(stop_after=2)
    t.add("a", links=10, added=3); t.add("b", links=0, added=0); t.add("c", links=5, added=0)
    assert not t.bot_check and t.zero_streak == 0 and t.total_added == 3
    t.add("d", links=0, added=0)
    assert not t.bot_check and t.zero_streak == 1
    t.add("e", links=0, added=0)
    assert t.bot_check and t.links == {"a": 10, "b": 0, "c": 5, "d": 0, "e": 0} and t.added["a"] == 3
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_discover.py -q`
Expected: FAIL — ImportError `SearchTally`.

- [ ] **Step 3: discover.py 수정**

import 에 `from .seeds import append_candidates, is_platform, read_keywords, read_seeds` (기존 줄 교체). `discover_search` 를 아래 세 정의로 바꾼다.

```python
class SearchTally:
    """키워드별 결과·추가 수. 결과 링크 0개가 stop_after 번 연속이면 Yahoo 봇 확인으로 보고 bot_check 를 켠다."""

    def __init__(self, stop_after: int = 2):
        self.stop_after = stop_after
        self.links: dict[str, int] = {}
        self.added: dict[str, int] = {}
        self.zero_streak = 0
        self.bot_check = False

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
                                   per_keyword: int = 20, stop_after_zero: int | None = 2) -> SearchTally:
    """키워드마다 새 브라우저 컨텍스트를 쓴다(같은 컨텍스트로 질의를 반복하면 Yahoo가 봇 확인 페이지로 보낸다).
    stop_after_zero 가 있으면 결과 0개가 그만큼 연속일 때 멈춘다(야간 루프). None 이면 끝까지 돈다(수동)."""
    tally = SearchTally(stop_after_zero if stop_after_zero else 10 ** 9)
    async with async_playwright() as pw:
        browser = await open_browser(pw)
        try:
            for kw in keywords:
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
    tally = await discover_search_keywords(settings, read_keywords(Path(keywords_path)), out_csv, known_domains, per_keyword, stop_after_zero=None)
    return tally.total_added
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/discover.py tests/test_discover.py
git commit -m "feat(crawler): search discover takes a keyword list, tallies per keyword and stops on bot check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: explore — 후보 선택, 선캡처, 커뮤니티 자동 등록, review.csv, 키워드 확장

**Files:**
- Create: `src/crawler/explore.py`, `tests/fixtures/site/community.html`, `tests/conftest.py`
- Modify: `tests/test_capture_integration.py` (픽스처를 conftest 로 이동)
- Test: `tests/test_explore.py`

**Interfaces:**
- Consumes: `run_capture(store=)`, `Store.rows_for / domain_dir`, `review.build_row / looks_like_community / write_review_csv`, `keywords.*`, `seeds.read_rows / update_notes / append_seed / read_keywords / write_keywords / load_blocklist`
- Produces:
  - `UNVERIFIED = "unverified"`
  - `@dataclass ExploreResult(precaptured: int, capture_summary: dict, review_rows: list[ReviewRow], review_csv: Path | None, auto_communities: list[str], keywords_added: list[str], keywords_retired: list[str], timed_out: bool)`
  - `select_candidates(candidates_csv: Path, max_n: int, blocklist: set[str] = frozenset()) -> list[Seed]`
  - `candidate_settings(settings) -> Settings`
  - `precapture(settings, seeds, store, budget_sec=None) -> tuple[dict, bool]`
  - `review_rows_for(store, seeds) -> list[ReviewRow]`
  - `register_communities(rows, community_csv, today, max_n) -> list[str]`
  - `expand_keywords(settings, seeds_dir, main_store, extra_titles) -> tuple[list[str], list[str]]`
  - `run_explore(settings, *, seeds_dir, out_dir, today, max_candidates=None, budget_sec=None) -> ExploreResult`

- [ ] **Step 1: 픽스처 공유를 위해 `tests/conftest.py` 를 만들고 통합 테스트에서 옮긴다**

`tests/conftest.py`:

```python
"""공용 픽스처: 로컬 픽스처 사이트 서버와 빠른 설정."""
import shutil
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from crawler.config import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "site"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    shutil.copytree(FIXTURES, root)
    for name, size, color in [("banner1.png", (720, 180), (220, 30, 30)), ("banner2.png", (720, 240), (30, 30, 220)),
                              ("banner3.png", (600, 200), (30, 160, 30)), ("icon.png", (48, 48), (0, 0, 0))]:
        Image.new("RGB", size, color).save(root / name)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def fast_settings(tmp_path) -> Settings:
    return Settings(out_root=tmp_path / "dataset", salt="test-salt", per_domain=2, concurrency=1,
                    delays={"gambling": 0.0, "embedded_banner": 0.0, "hard_negative": 0.0, "normal": 0.0, "candidate": 0.0})
```

`tests/test_capture_integration.py` 에서 `QuietHandler`, `site`, `fast_settings`, `FIXTURES` 정의와 그에만 쓰이던 import(`shutil`, `socket`, `threading`, `partial`, `http.server`, `pytest`, `Settings`)를 지우고 `from tests.conftest import fast_settings` 를 추가한다. (`site` 는 conftest 픽스처라 import 없이 쓰인다.)

Run: `.venv/bin/pytest tests/test_capture_integration.py -q` → 기존과 같이 PASS.

- [ ] **Step 2: 커뮤니티 픽스처 추가** — `tests/fixtures/site/community.html`

```html
<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>먹튀검증 커뮤니티 테스트</title></head>
<body>
<h1>보증업체 목록</h1>
<p>먹튀검증을 마친 보증업체를 소개합니다. 커뮤니티 회원이 직접 검증합니다.</p>
<ul>
<li><a href="https://ext1.com/?code=a1">업체 1</a></li>
<li><a href="https://ext2.net/">업체 2</a></li>
<li><a href="https://ext3.com/">업체 3</a></li>
<li><a href="https://ext4.net/">업체 4</a></li>
<li><a href="https://ext5.com/">업체 5</a></li>
<li><a href="https://ext6.net/">업체 6</a></li>
<li><a href="https://ext7.com/">업체 7</a></li>
<li><a href="https://ext8.net/">업체 8</a></li>
<li><a href="https://ext9.com/">업체 9</a></li>
<li><a href="https://ext10.net/">업체 10</a></li>
</ul>
<nav><a href="/page2.html">공지</a></nav>
</body></html>
```

- [ ] **Step 3: 실패하는 테스트 작성** — `tests/test_explore.py`

```python
from pathlib import Path

from crawler.explore import run_explore, select_candidates
from crawler.seeds import read_keywords, read_rows, write_rows
from tests.conftest import fast_settings


def make_seeds(tmp_path, candidates):
    sd = tmp_path / "seeds"; sd.mkdir()
    write_rows(sd / "candidates.csv", candidates)
    (sd / "keywords.txt").write_text("토토사이트\n", encoding="utf-8")
    (sd / "community_lists.csv").write_text("url,source,added_at,note\n", encoding="utf-8")
    (sd / "blocklist.txt").write_text("", encoding="utf-8")
    return sd


def cand(url, added_at="2026-10-19", note="unverified", source="search:a"):
    return {"url": url, "source": source, "added_at": added_at, "note": note}


def test_select_candidates_filters_unverified_newest_first(tmp_path):
    sd = make_seeds(tmp_path, [cand("https://old.com/", "2026-10-01"), cand("https://done.com/", "2026-10-05", note="→ gambling.csv (검토)"),
                               cand("https://new.com/"), cand("https://www.new.com/dup"), cand("https://bad.com/")])
    got = select_candidates(sd / "candidates.csv", max_n=5, blocklist={"bad.com"})
    assert [s.url for s in got] == ["https://new.com/", "https://old.com/"]
    assert [s.url for s in select_candidates(sd / "candidates.csv", max_n=1)] == ["https://new.com/"]
    assert select_candidates(tmp_path / "missing.csv", max_n=5) == []


async def test_run_explore_precaptures_suggests_and_registers_community(site, tmp_path):
    settings = fast_settings(tmp_path)
    sd = make_seeds(tmp_path, [cand(site + "/community.html", source="search:먹튀검증")])
    out = tmp_path / "out" / "2026-10-20"
    res = await run_explore(settings, seeds_dir=sd, out_dir=out, today="2026-10-20")
    assert res.precaptured == 1 and res.timed_out is False and res.capture_summary["ok"] == 2
    r = res.review_rows[0]
    assert r.domain == "127.0.0.1" and r.status == "ok" and r.suggested == "community" and "many_ext" in r.signals
    assert Path(r.review_dir).is_dir() and Path(r.review_dir).parent.name == "candidate" and Path(r.review_dir).parent.parent == settings.review_root
    assert res.auto_communities == ["127.0.0.1"]
    comm = read_rows(sd / "community_lists.csv")
    assert comm[0] == {"url": site + "/community.html", "source": "auto:2026-10-20", "added_at": "2026-10-20", "note": "자동 등록(미검토)"}
    assert read_rows(sd / "candidates.csv")[0]["note"] == "review: 2026-10-20"
    assert res.review_csv == out / "review.csv" and (out / "review.csv").read_text(encoding="utf-8").count("\n") == 2
    assert not (settings.out_root / "index.jsonl").exists()   # 본 데이터셋은 건드리지 않는다
    res2 = await run_explore(settings, seeds_dir=sd, out_dir=tmp_path / "out" / "2026-10-21", today="2026-10-21")
    assert res2.precaptured == 0 and res2.review_rows == [] and (tmp_path / "out" / "2026-10-21" / "review.csv").exists()


async def test_run_explore_suggests_gambling_and_expands_keywords(site, tmp_path):
    settings = fast_settings(tmp_path)
    sd = make_seeds(tmp_path, [cand(site + "/", source="search:토토사이트")])
    res = await run_explore(settings, seeds_dir=sd, out_dir=tmp_path / "out" / "d", today="2026-10-20")
    r = res.review_rows[0]
    assert r.suggested == "gambling" and {"deposit_page", "menu_terms"} <= set(r.signals) and res.auto_communities == []
    assert res.keywords_added == ["도박 사이트"] and res.keywords_retired == []      # 제목 "테스트 도박 사이트" 에서
    assert read_keywords(sd / "keywords_auto.txt") == ["도박 사이트"]
    assert (sd / "explore_state.json").exists()


async def test_run_explore_budget_timeout_keeps_partial_results(site, tmp_path):
    settings = fast_settings(tmp_path)
    sd = make_seeds(tmp_path, [cand(site + "/")])
    out = tmp_path / "out" / "t"
    res = await run_explore(settings, seeds_dir=sd, out_dir=out, today="2026-10-20", budget_sec=0.01)
    assert res.timed_out is True and res.capture_summary == {} and res.precaptured in (0, 1)
    assert (out / "review.csv").exists()
```

- [ ] **Step 4: 실패 확인**

Run: `.venv/bin/pytest tests/test_explore.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawler.explore'`.

- [ ] **Step 5: explore.py 작성**

```python
"""시드 탐색: 후보 선캡처(리뷰 루트) → 신호·추천 → 커뮤니티 자동 등록 → review.csv → candidates note 갱신 → 키워드 확장."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path

from .capture import run_capture
from .config import CANDIDATE_LABEL, Settings
from .domains import registrable_domain
from .keywords import AUTO_HEADER, expand, extract_terms, load_state, save_state
from .review import ReviewRow, build_row, looks_like_community, write_review_csv
from .seeds import Seed, append_seed, load_blocklist, read_keywords, read_rows, update_notes, write_keywords
from .store import Store

UNVERIFIED = "unverified"


@dataclass
class ExploreResult:
    precaptured: int = 0
    capture_summary: dict = field(default_factory=dict)
    review_rows: list[ReviewRow] = field(default_factory=list)
    review_csv: Path | None = None
    auto_communities: list[str] = field(default_factory=list)
    keywords_added: list[str] = field(default_factory=list)
    keywords_retired: list[str] = field(default_factory=list)
    timed_out: bool = False


def select_candidates(candidates_csv: Path, max_n: int, blocklist: set[str] = frozenset()) -> list[Seed]:
    """note 가 unverified 인 후보를 added_at 최신순(같은 날짜는 파일 순서)으로 max_n개. 같은 등록 도메인은 첫 행만."""
    rows = [r for r in read_rows(candidates_csv) if r["note"] == UNVERIFIED and registrable_domain(r["url"]) not in blocklist]
    rows.sort(key=lambda r: r["added_at"], reverse=True)
    out: list[Seed] = []
    seen: set[str] = set()
    for r in rows:
        d = registrable_domain(r["url"])
        if d in seen:
            continue
        seen.add(d)
        out.append(Seed(url=r["url"], source=r["source"], added_at=r["added_at"], note=r["note"]))
        if len(out) >= max_n:
            break
    return out


def candidate_settings(settings: Settings) -> Settings:
    """후보는 라벨을 모르는 사이트: 도메인당 nightly_candidate_pages 페이지, 메뉴 클릭 없음(robots·5초는 config 가 candidate 라벨에 적용)."""
    return replace(settings, per_domain=settings.nightly_candidate_pages, click_menus=False, refresh=False)


async def precapture(settings: Settings, seeds: list[Seed], store: Store, budget_sec: float | None = None) -> tuple[dict, bool]:
    """후보를 candidate 라벨로 리뷰 루트에 캡처한다. 예산이 끝나면 중단한다. (요약, 중단 여부). 중단돼도 그때까지의 행은 store 에 남아 있다."""
    coro = run_capture(candidate_settings(settings), seeds, label=CANDIDATE_LABEL, store=store)
    if budget_sec is None:
        return await coro, False
    try:
        return await asyncio.wait_for(coro, timeout=budget_sec), False
    except asyncio.TimeoutError:
        return {}, True


def review_rows_for(store: Store, seeds: list[Seed]) -> list[ReviewRow]:
    rows: list[ReviewRow] = []
    for s in seeds:
        d = registrable_domain(s.url)
        metas = store.rows_for(CANDIDATE_LABEL, d)
        if not metas:
            continue   # 예산 안에 못 간 후보는 note 가 그대로라 다음 밤에 다시 고른다
        rows.append(build_row(d, s.url, metas, str(store.domain_dir(CANDIDATE_LABEL, d))))
    return rows


def register_communities(rows: list[ReviewRow], community_csv: Path, today: str, max_n: int) -> list[str]:
    added: list[str] = []
    for r in rows:
        if len(added) >= max_n:
            break
        if looks_like_community(r.signals) and append_seed(community_csv, r.url, source=f"auto:{today}", note="자동 등록(미검토)", added_at=today):
            added.append(r.domain)
    return added


def expand_keywords(settings: Settings, seeds_dir: Path, main_store: Store, extra_titles: list[str]) -> tuple[list[str], list[str]]:
    """본 데이터셋의 gambling ok 제목 + 오늘 선캡처 제목에서 용어를 뽑아 keywords_auto.txt 와 explore_state.json 을 갱신한다."""
    seeds_dir = Path(seeds_dir)
    manual = read_keywords(seeds_dir / "keywords.txt")
    auto_path = seeds_dir / "keywords_auto.txt"
    auto = read_keywords(auto_path)
    state_path = seeds_dir / "explore_state.json"
    state = load_state(state_path)
    retired = {kw for kw, info in state["keywords"].items() if info.get("retired")}
    titles = [m.get("title") or "" for m in main_store.load_index() if m["label"] == "gambling" and m["status"] == "ok"] + extra_titles
    terms = extract_terms(titles, known=set(manual) | set(auto) | retired)
    new, added, retired_now = expand(state, auto, terms, add_per_day=settings.auto_keyword_add_per_day,
                                     pool=settings.auto_keyword_pool, retire_streak=settings.auto_keyword_retire_streak)
    write_keywords(auto_path, new, AUTO_HEADER)
    save_state(state_path, state)
    return added, retired_now


async def run_explore(settings: Settings, *, seeds_dir: Path, out_dir: Path, today: str,
                      max_candidates: int | None = None, budget_sec: float | None = None) -> ExploreResult:
    seeds_dir = Path(seeds_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = ExploreResult()
    candidates_csv = seeds_dir / "candidates.csv"
    seeds = select_candidates(candidates_csv, max_candidates or settings.nightly_max_candidates, load_blocklist(seeds_dir / "blocklist.txt"))
    review_store = Store(settings.review_root, settings.salt)
    if seeds:
        res.capture_summary, res.timed_out = await precapture(settings, seeds, review_store, budget_sec)
    res.review_rows = review_rows_for(review_store, seeds)
    res.precaptured = len(res.review_rows)
    res.auto_communities = register_communities(res.review_rows, seeds_dir / "community_lists.csv", today, settings.nightly_max_auto_communities)
    res.review_csv = out_dir / "review.csv"
    write_review_csv(res.review_csv, res.review_rows)
    update_notes(candidates_csv, {r.domain: f"review: {today}" for r in res.review_rows})
    res.keywords_added, res.keywords_retired = expand_keywords(
        settings, seeds_dir, Store(settings.out_root, settings.salt), [r.title for r in res.review_rows if r.status == "ok"])
    return res
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/bin/pytest -q`
Expected: 전부 PASS. (`test_run_explore_suggests_gambling_and_expands_keywords` 가 `keywords_added` 로 실패하면 픽스처 제목 "테스트 도박 사이트" 의 토큰화를 확인한다: 기대 용어는 2토큰 "도박 사이트" 하나뿐이다.)

- [ ] **Step 7: 커밋**

```bash
git add src/crawler/explore.py tests/test_explore.py tests/conftest.py tests/test_capture_integration.py tests/fixtures/site/community.html
git commit -m "feat(crawler): explore — precapture candidates into review root, auto-register communities, write review.csv, expand keywords

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: promote — review.csv 판정 반영

**Files:**
- Create: `src/crawler/promote.py`
- Test: `tests/test_promote.py`

**Interfaces:**
- Consumes: `review.read_review_csv / VERDICTS / ReviewRow`, `Store.rows_for / domain_dir / adopt_domain / remove_domain`, `seeds.append_seed / update_source / remove_domain / update_notes / read_rows`
- Produces:
  - 상수 `SKIP, PROMOTE, COMMUNITY, EXCLUDE, BLOCKED, DONE = "skip", "promote", "community", "exclude", "blocked", "already"`
  - `@dataclass Action(row: ReviewRow, kind: str, detail: str)`
  - `plan_promotion(rows: list[ReviewRow]) -> list[Action]` — 허용되지 않은 verdict 가 있으면 `ValueError`
  - `apply_promotion(actions, settings, seeds_dir, today) -> dict[str, int]`
  - `run_promote(csv_path, settings, seeds_dir, *, today, dry_run=False) -> int` (0 적용/드라이런, 1 거부)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_promote.py`

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.config import Settings
from crawler.promote import plan_promotion, run_promote
from crawler.review import ReviewRow, read_review_csv, write_review_csv
from crawler.seeds import read_rows, write_rows
from crawler.store import Store, ts_label

KST = timezone(timedelta(hours=9))
AT = datetime(2026, 10, 20, 4, 30, tzinfo=KST)


def settings_for(tmp_path):
    return Settings(out_root=tmp_path / "dataset", salt="s")


def make_review(settings, domain):
    """리뷰 루트에 홈+내부 페이지 ok 행 2개와 PNG 를 만들고 폴더 경로를 돌려준다."""
    review = Store(settings.review_root, settings.salt)
    h = review.hash_of(domain)
    for idx in (0, 1):
        stem = f"{ts_label(AT)}_{idx}"
        review.record({"id": f"{h}_{stem}", "label": "candidate", "domain": domain, "domain_hash": h, "status": "ok",
                       "url": f"https://{domain}/{idx}", "url_norm": f"https://{domain}/{idx}", "phash": "0" * 64, "captured_at": AT.isoformat(),
                       "full_path": f"candidate/{h}/{stem}_full.png", "banners": [{"path": f"candidate/{h}/{stem}_b0.png", "external": False}]})
        d = review.domain_dir("candidate", domain)
        (d / f"{stem}_full.png").write_bytes(b"png"); (d / f"{stem}_b0.png").write_bytes(b"png")
    return str(review.domain_dir("candidate", domain))


def make_seeds(tmp_path, domains):
    sd = tmp_path / "seeds"; sd.mkdir()
    write_rows(sd / "candidates.csv", [{"url": f"https://{d}/", "source": "search:x", "added_at": "2026-10-19", "note": "review: 2026-10-20"} for d in domains])
    write_rows(sd / "community_lists.csv", [
        {"url": "https://autocomm.com/", "source": "auto:2026-10-20", "added_at": "2026-10-20", "note": "자동 등록(미검토)"},
        {"url": "https://autoex.com/", "source": "auto:2026-10-20", "added_at": "2026-10-20", "note": "자동 등록(미검토)"}])
    return sd


def rr(domain, verdict, review_dir, note=""):
    return ReviewRow(domain=domain, url=f"https://{domain}/", title="t", status="ok", signals=[], suggested="", verdict=verdict, note=note, review_dir=review_dir)


def test_promote_applies_each_verdict_and_is_idempotent(tmp_path):
    settings = settings_for(tmp_path)
    domains = ["g.com", "autocomm.com", "autoex.com", "b.com", "later.com"]
    sd = make_seeds(tmp_path, domains)
    dirs = {d: make_review(settings, d) for d in domains}
    csv_path = tmp_path / "review.csv"
    write_review_csv(csv_path, [rr("g.com", "gambling", dirs["g.com"], note="운영 사이트"), rr("autocomm.com", "community", dirs["autocomm.com"]),
                                rr("autoex.com", "exclude", dirs["autoex.com"]), rr("b.com", "blocked", dirs["b.com"]), rr("later.com", "", dirs["later.com"])])
    assert run_promote(csv_path, settings, sd, today="2026-10-20") == 0
    main = Store(settings.out_root, settings.salt); review = Store(settings.review_root, settings.salt)
    g = read_rows(sd / "gambling.csv")[0]
    assert g == {"url": "https://g.com/", "source": "review:2026-10-20", "added_at": "2026-10-20", "note": "운영 사이트"}
    assert main.ok_count("gambling", "g.com") == 2 and review.rows_for("candidate", "g.com") == [] and not Path(dirs["g.com"]).exists()
    assert (main.domain_dir("gambling", "g.com") / f"{ts_label(AT)}_0_full.png").exists()
    assert main.rows_for("gambling", "g.com")[0]["full_path"].startswith(f"gambling/{main.hash_of('g.com')}/")
    comm = read_rows(sd / "community_lists.csv")
    assert [c["url"] for c in comm] == ["https://autocomm.com/"] and comm[0]["source"] == "review:2026-10-20"   # 줄 추가 없이 source 갱신, autoex 는 삭제
    assert not Path(dirs["autocomm.com"]).exists() and not Path(dirs["autoex.com"]).exists() and not Path(dirs["b.com"]).exists()
    assert Path(dirs["later.com"]).exists() and review.rows_for("candidate", "later.com") != []
    notes = {c["url"]: c["note"] for c in read_rows(sd / "candidates.csv")}
    assert notes == {"https://g.com/": "→ gambling.csv (review 2026-10-20)", "https://autocomm.com/": "→ community_lists.csv (review 2026-10-20)",
                     "https://autoex.com/": "excluded: 검토 제외", "https://b.com/": "blocked_kr 2026-10-20", "https://later.com/": "review: 2026-10-20"}
    actions = plan_promotion(read_review_csv(csv_path))
    assert [a.kind for a in actions] == ["already", "already", "already", "already", "skip"]
    assert run_promote(csv_path, settings, sd, today="2026-10-21") == 0 and read_rows(sd / "gambling.csv") == [g]


def test_promote_rejects_bad_verdict_and_dry_run_changes_nothing(tmp_path):
    settings = settings_for(tmp_path)
    sd = make_seeds(tmp_path, ["g.com"])
    d = make_review(settings, "g.com")
    csv_path = tmp_path / "review.csv"
    write_review_csv(csv_path, [rr("g.com", "gamblin", d)])
    assert run_promote(csv_path, settings, sd, today="2026-10-20") == 1 and Path(d).exists()
    write_review_csv(csv_path, [rr("g.com", "gambling", d)])
    assert run_promote(csv_path, settings, sd, today="2026-10-20", dry_run=True) == 0
    assert Path(d).exists() and not (sd / "gambling.csv").exists() and read_rows(sd / "candidates.csv")[0]["note"] == "review: 2026-10-20"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_promote.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawler.promote'`.

- [ ] **Step 3: promote.py 작성**

```python
"""review.csv 판정 반영: 시드 추가, 리뷰 폴더를 본 데이터셋으로 이동(라벨·경로 재기록), candidates.csv note 갱신. 두 번 돌려도 안전하다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import CANDIDATE_LABEL, LABELS, Settings
from .domains import registrable_domain
from .review import VERDICTS, ReviewRow, read_review_csv
from .seeds import append_seed, read_rows, remove_domain, update_notes, update_source
from .store import Store

SKIP, PROMOTE, COMMUNITY, EXCLUDE, BLOCKED, DONE = "skip", "promote", "community", "exclude", "blocked", "already"


@dataclass
class Action:
    row: ReviewRow
    kind: str
    detail: str


def plan_promotion(rows: list[ReviewRow]) -> list[Action]:
    bad = [(i + 2, r.verdict) for i, r in enumerate(rows) if r.verdict not in VERDICTS]   # +2: 헤더 다음이 2행
    if bad:
        raise ValueError("허용되지 않은 verdict: " + ", ".join(f"{n}행 '{v}'" for n, v in bad))
    out: list[Action] = []
    for r in rows:
        if r.verdict == "":
            out.append(Action(r, SKIP, "판정 없음"))
        elif r.review_dir and not Path(r.review_dir).exists():
            out.append(Action(r, DONE, "리뷰 폴더 없음(이미 처리됨)"))
        elif r.verdict in LABELS:
            out.append(Action(r, PROMOTE, f"seeds/{r.verdict}.csv 추가 + 폴더를 {r.verdict}/ 로 이동"))
        elif r.verdict == "community":
            out.append(Action(r, COMMUNITY, "community_lists.csv 추가(있으면 source 갱신) + 리뷰 삭제"))
        elif r.verdict == "exclude":
            out.append(Action(r, EXCLUDE, "리뷰 삭제 + candidates note 'excluded'"))
        else:
            out.append(Action(r, BLOCKED, "리뷰 삭제 + candidates note 'blocked_kr'"))
    return out


def apply_promotion(actions: list[Action], settings: Settings, seeds_dir: Path, today: str) -> dict[str, int]:
    seeds_dir = Path(seeds_dir)
    review = Store(settings.review_root, settings.salt)
    main = Store(settings.out_root, settings.salt)
    candidates = seeds_dir / "candidates.csv"
    community = seeds_dir / "community_lists.csv"
    counts = {k: 0 for k in (SKIP, PROMOTE, COMMUNITY, EXCLUDE, BLOCKED, DONE)}
    notes: dict[str, str] = {}
    for a in actions:
        r = a.row
        counts[a.kind] += 1
        if a.kind in (SKIP, DONE):
            continue
        if a.kind == PROMOTE:
            append_seed(seeds_dir / f"{r.verdict}.csv", r.url, source=f"review:{today}", note=r.note or "nightly 승격", added_at=today)
            rows = review.rows_for(CANDIDATE_LABEL, r.domain)
            if rows:
                main.adopt_domain(review.domain_dir(CANDIDATE_LABEL, r.domain), rows, r.verdict)
            review.remove_domain(CANDIDATE_LABEL, r.domain)
            notes[r.domain] = f"→ {r.verdict}.csv (review {today})"
        elif a.kind == COMMUNITY:
            if not append_seed(community, r.url, source=f"review:{today}", note=r.note or "검토 승인", added_at=today):
                update_source(community, r.domain, f"review:{today}")
            review.remove_domain(CANDIDATE_LABEL, r.domain)
            notes[r.domain] = f"→ community_lists.csv (review {today})"
        elif a.kind == EXCLUDE:
            review.remove_domain(CANDIDATE_LABEL, r.domain)
            if any(registrable_domain(c["url"]) == r.domain and c["source"].startswith("auto:") for c in read_rows(community)):
                remove_domain(community, r.domain)   # 자동 등록된 커뮤니티를 사람이 되돌린 것
            notes[r.domain] = f"excluded: {r.note or '검토 제외'}"
        elif a.kind == BLOCKED:
            review.remove_domain(CANDIDATE_LABEL, r.domain)
            notes[r.domain] = f"blocked_kr {today}"
    update_notes(candidates, notes)
    return counts


def run_promote(csv_path: Path, settings: Settings, seeds_dir: Path, *, today: str, dry_run: bool = False) -> int:
    rows = read_review_csv(csv_path)
    try:
        actions = plan_promotion(rows)
    except ValueError as e:
        print(f"거부: {e}")
        return 1
    for a in actions:
        print(f"[{a.kind}] {a.row.domain} verdict={a.row.verdict or '-'} — {a.detail}")
    if dry_run:
        print("(dry-run: 아무것도 바꾸지 않았습니다)")
        return 0
    counts = apply_promotion(actions, settings, seeds_dir, today)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    return 0
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_promote.py -q`
Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/promote.py tests/test_promote.py
git commit -m "feat(crawler): promote — apply review.csv verdicts to seeds and dataset

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: nightly — 단계 실행기, 잠금, 집계, 썸네일, 보고서, 정리

**Files:**
- Create: `src/crawler/nightly.py`
- Test: `tests/test_nightly.py`

**Interfaces:**
- Consumes: `discover_search_keywords`, `discover_community`, `run_explore`, `select_candidates`, `run_capture`, `keywords.load_state / pick_auto_keywords / record_run / save_state`, `seeds.*`, `stats.STATUSES`, `Store`
- Produces:
  - `WORK_STAGES = ("search", "community", "explore", "capture")`, 상태 `OK, PARTIAL, FAILED, SKIPPED = "ok", "partial", "failed", "skipped"`
  - `@dataclass StageResult(name, status, elapsed: float, counts: dict, error: str | None)`
  - `StageFn = Callable[[float], Awaitable[dict]]` (인자 = 예산 초; 결과 dict 에 `timed_out: True` 가 있으면 partial)
  - `class Runner(settings, *, seeds_dir, out_base, today, only=None, skip=None, budget_min=90, dry_run=False, stages=None, grace_sec=5.0)` — `.run() -> int`, `.results`, `.explore_result`, `.out_dir`, `.dry_run_plan() -> str`, `.exit_code() -> int`
  - `acquire_lock(path) -> bool`, `release_lock(path) -> None`, `pid_alive(pid) -> bool`
  - `daily_counts(rows, today) -> dict[label, {status…, total_ok}]`, `stale_review_count(rows, today, days) -> int`
  - `make_thumbs(rows: list[ReviewRow], thumbs_dir) -> dict[domain, 상대경로]`, `prune_out(out_base, today, keep_days) -> list[str]`
  - `build_report(*, today, results, daily, review_rows, thumbs, explore, stale_reviews, pruned, exit_code) -> str`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_nightly.py`

```python
import asyncio
import json
import os

from PIL import Image

from crawler.config import Settings
from crawler.nightly import Runner, acquire_lock, daily_counts, make_thumbs, prune_out, release_lock, stale_review_count
from crawler.review import ReviewRow


async def ok_stage(budget):
    return {"x": 1}


async def fail_stage(budget):
    raise RuntimeError("boom")


async def slow_stage(budget):
    await asyncio.sleep(budget + 10)
    return {}


def tiny_settings(tmp_path):
    return Settings(out_root=tmp_path / "dataset", salt="s",
                    nightly_budget_min={"search": 0.01, "community": 0.01, "explore": 0.01, "capture": 0.01})


async def test_runner_isolates_stages_and_writes_report(tmp_path):
    settings = tiny_settings(tmp_path)
    stages = {"search": ok_stage, "community": fail_stage, "explore": slow_stage, "capture": ok_stage}
    r = Runner(settings, seeds_dir=tmp_path / "seeds", out_base=tmp_path / "out", today="2026-10-20", stages=stages, grace_sec=0.1)
    assert await r.run() == 1
    assert [x.status for x in r.results] == ["ok", "failed", "partial", "ok"] and [x.name for x in r.results] == ["search", "community", "explore", "capture"]
    assert "RuntimeError: boom" in r.results[1].error and r.results[0].counts == {"x": 1}
    out = tmp_path / "out" / "2026-10-20"
    report = (out / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# 야간 수집 보고서 2026-10-20") and "## 단계 결과" in report and "## 실패·경고" in report and "boom" in report
    assert "| gambling | 0 | 0 | 0 | 0 | 0 | 0 |" in report
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["exit_code"] == 1 and [s["status"] for s in summary["stages"]] == ["ok", "failed", "partial", "ok"] and summary["review_pending"] == 0
    assert (out / "run.log").read_text(encoding="utf-8").count("▶") == 4


async def test_runner_only_skip_and_exit_zero(tmp_path):
    settings = tiny_settings(tmp_path)
    stages = {s: ok_stage for s in ("search", "community", "explore", "capture")}
    r = Runner(settings, seeds_dir=tmp_path / "seeds", out_base=tmp_path / "out", today="2026-10-20", only=["search", "capture"], skip=["capture"], stages=stages)
    assert await r.run() == 0
    assert [(x.name, x.status) for x in r.results] == [("search", "ok"), ("community", "skipped"), ("explore", "skipped"), ("capture", "skipped")]


def test_lock_blocks_live_pid_and_clears_stale(tmp_path):
    lock = tmp_path / "out" / ".lock"
    assert acquire_lock(lock) and lock.read_text() == str(os.getpid())
    assert not acquire_lock(lock)
    release_lock(lock)
    lock.write_text("999999999")
    assert acquire_lock(lock) and lock.read_text() == str(os.getpid())
    release_lock(lock)
    assert not lock.exists()


def test_daily_counts_stale_reviews_and_prune(tmp_path):
    rows = [{"label": "gambling", "domain": "a.com", "status": "ok", "captured_at": "2026-10-20T04:31:00+09:00"},
            {"label": "gambling", "domain": "a.com", "status": "duplicate", "captured_at": "2026-10-20T04:32:00+09:00"},
            {"label": "gambling", "domain": "b.com", "status": "ok", "captured_at": "2026-10-01T04:32:00+09:00"},
            {"label": "normal", "domain": "n.com", "status": "blocked_kr", "captured_at": "2026-10-20T05:00:00+09:00"},
            {"label": "candidate", "domain": "c.com", "status": "ok", "captured_at": "2026-09-01T05:00:00+09:00"}]
    d = daily_counts(rows, "2026-10-20")
    assert d["gambling"]["ok"] == 1 and d["gambling"]["duplicate"] == 1 and d["gambling"]["total_ok"] == 2
    assert d["normal"]["blocked_kr"] == 1 and d["normal"]["total_ok"] == 0 and "candidate" not in d
    assert stale_review_count(rows, "2026-10-20", 30) == 1 and stale_review_count(rows, "2026-09-05", 30) == 0
    out = tmp_path / "out"
    for name in ("2026-09-01", "2026-10-19", "junk"):
        (out / name / "thumbs").mkdir(parents=True)
        (out / name / "report.md").write_text("x"); (out / name / "review.csv").write_text("y"); (out / name / "thumbs" / "a.png").write_bytes(b"p")
    assert prune_out(out, "2026-10-20", keep_days=30) == ["2026-09-01"]
    assert not (out / "2026-09-01" / "report.md").exists() and (out / "2026-09-01" / "review.csv").exists() and not (out / "2026-09-01" / "thumbs").exists()
    assert (out / "2026-10-19" / "report.md").exists() and (out / "junk" / "report.md").exists()


def test_make_thumbs_crops_first_viewport(tmp_path):
    d = tmp_path / "_review" / "candidate" / "abc"; d.mkdir(parents=True)
    Image.new("RGB", (824, 6000), (200, 50, 50)).save(d / "20261020T043000_0_full.png")
    rows = [ReviewRow(domain="a.com", url="https://a.com/", title="", status="ok", review_dir=str(d)),
            ReviewRow(domain="none.com", url="https://none.com/", title="", status="blocked_kr", review_dir=str(tmp_path / "nope"))]
    got = make_thumbs(rows, tmp_path / "out" / "thumbs")
    assert got == {"a.com": "thumbs/abc.png"}
    w, h = Image.open(tmp_path / "out" / "thumbs" / "abc.png").size
    assert w == 160 and h == 355   # 첫 화면(1830px)만 잘라 160px 폭으로
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_nightly.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawler.nightly'`.

- [ ] **Step 3: nightly.py 작성**

```python
"""야간 루프 실행기: search → community → explore → capture 를 예산 안에서 격리 실행하고 보고서를 쓴다.
이 Mac 에는 timeout 명령이 없으므로 시간 예산은 asyncio.wait_for 로 건다."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import traceback
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from PIL import Image

from .capture import run_capture
from .config import LABELS, Settings
from .discover import discover_community, discover_search_keywords
from .domains import registrable_domain
from .explore import ExploreResult, run_explore, select_candidates
from .keywords import load_state, pick_auto_keywords, record_run, save_state
from .review import ReviewRow
from .seeds import all_seed_files, load_blocklist, read_keywords, read_seeds, seed_domains
from .stats import STATUSES
from .store import Store

WORK_STAGES = ("search", "community", "explore", "capture")
OK, PARTIAL, FAILED, SKIPPED = "ok", "partial", "failed", "skipped"
THUMB_WIDTH = 160
FIRST_VIEWPORT_PX = 1830    # 412×915 CSS px × DPR 2 의 높이
KEEP_OUT_DAYS = 30
STALE_REVIEW_DAYS = 30
BUDGET_EXHAUSTED = "예산 소진"
StageFn = Callable[[float], Awaitable[dict]]


@dataclass
class StageResult:
    name: str
    status: str
    elapsed: float = 0.0
    counts: dict = field(default_factory=dict)
    error: str | None = None


# ---------- 잠금 ----------

def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(path: Path) -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = -1
        if pid > 0 and pid_alive(pid):
            return False
        path.unlink()
    path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_lock(path: Path) -> None:
    Path(path).unlink(missing_ok=True)


# ---------- 집계·보고서 재료 ----------

def daily_counts(rows: list[dict], today: str) -> dict[str, dict[str, int]]:
    out = {lab: {**{s: 0 for s in STATUSES}, "total_ok": 0} for lab in LABELS}
    for m in rows:
        lab = m.get("label")
        if lab not in out:
            continue
        if m.get("status") == "ok":
            out[lab]["total_ok"] += 1
        if str(m.get("captured_at", ""))[:10] == today:
            out[lab][m["status"]] = out[lab].get(m["status"], 0) + 1
    return out


def stale_review_count(rows: list[dict], today: str, days: int) -> int:
    latest: dict[str, str] = {}
    for m in rows:
        d = m.get("domain", "")
        latest[d] = max(latest.get(d, ""), str(m.get("captured_at", ""))[:10])
    t = date.fromisoformat(today)
    return sum(1 for day in latest.values() if day and (t - date.fromisoformat(day)).days > days)


def make_thumbs(rows: list[ReviewRow], thumbs_dir: Path) -> dict[str, str]:
    """홈 전체 화면 PNG 의 첫 화면(1830px)을 160px 폭으로 줄인다. 도메인 → 'thumbs/<폴더명>.png'."""
    thumbs_dir = Path(thumbs_dir)
    out: dict[str, str] = {}
    for r in rows:
        d = Path(r.review_dir) if r.review_dir else None
        fulls = sorted(d.glob("*_0_full.png")) if d and d.is_dir() else []
        if not fulls:
            continue
        try:
            thumbs_dir.mkdir(parents=True, exist_ok=True)
            with Image.open(fulls[-1]) as im:
                im = im.convert("RGB").crop((0, 0, im.width, min(im.height, FIRST_VIEWPORT_PX)))
                h = max(1, round(im.height * THUMB_WIDTH / im.width))
                im.resize((THUMB_WIDTH, h)).save(thumbs_dir / f"{d.name}.png")
            out[r.domain] = f"thumbs/{d.name}.png"
        except Exception:
            continue
    return out


def prune_out(out_base: Path, today: str, keep_days: int) -> list[str]:
    """keep_days 지난 날짜 폴더에서 review.csv 만 남기고 지운다."""
    out_base = Path(out_base)
    t = date.fromisoformat(today)
    pruned: list[str] = []
    if not out_base.exists():
        return pruned
    for d in sorted(out_base.iterdir()):
        try:
            when = date.fromisoformat(d.name)
        except ValueError:
            continue
        if not d.is_dir() or (t - when).days <= keep_days:
            continue
        for p in d.iterdir():
            if p.name == "review.csv":
                continue
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        pruned.append(d.name)
    return pruned


def _cell(text: str, limit: int = 40) -> str:
    t = " ".join((text or "").split()).replace("|", "\\|")
    return t if len(t) <= limit else t[:limit - 1] + "…"


def _brief(counts: dict) -> str:
    return _cell(json.dumps(counts, ensure_ascii=False), 200)


def build_report(*, today: str, results: list[StageResult], daily: dict, review_rows: list[ReviewRow], thumbs: dict[str, str],
                 explore: ExploreResult | None, stale_reviews: int, pruned: list[str], exit_code: int) -> str:
    by = {r.name: r for r in results}
    new_ok = {lab: daily[lab]["ok"] for lab in LABELS}
    failed = [r.name for r in results if r.status in (FAILED, PARTIAL)]
    lines = [f"# 야간 수집 보고서 {today}", "", "## 요약",
             "- 단계: " + " · ".join(f"{r.name} {r.status}" for r in results) + f" (종료 코드 {exit_code})",
             f"- 새 ok 화면 {sum(new_ok.values())}장 (" + " · ".join(f"{lab} {n}" for lab, n in new_ok.items()) + f"), 선캡처 후보 {len(review_rows)} 도메인",
             f"- 아침에 볼 것: 검토 대기 {len(review_rows)}건 → review.csv" + (f" / 실패·부분 단계: {', '.join(failed)}" if failed else " / 실패 없음"),
             "", "## 단계 결과", "| 단계 | 상태 | 소요 | 핵심 수치 |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.name} | {r.status} | {r.elapsed / 60:.1f}분 | {_brief(r.counts)} |")
    lines += ["", "## 라벨별 전일 대비", "| 라벨 | 오늘 ok | duplicate | blocked_kr | challenge | error | 누적 ok |", "|---|---|---|---|---|---|---|"]
    for lab in LABELS:
        d = daily[lab]
        lines.append(f"| {lab} | {d['ok']} | {d['duplicate']} | {d['blocked_kr']} | {d['challenge']} | {d['error']} | {d['total_ok']} |")
    lines += ["", f"## 검토 대기 ({len(review_rows)})", "",
              "판정은 `review.csv` 의 `verdict` 열(gambling · embedded_banner · hard_negative · normal · community · exclude · blocked)에 적고 "
              "`python -m crawler promote out/<날짜>/review.csv` 를 실행한다.", "",
              "| 썸네일 | 도메인 | 제목 | 상태 | 신호 | 추천 |", "|---|---|---|---|---|---|"]
    for r in review_rows[:40]:
        thumb = f"![]({thumbs[r.domain]})" if r.domain in thumbs else ""
        lines.append(f"| {thumb} | {r.domain} | {_cell(r.title)} | {r.status} | {' '.join(r.signals)} | {r.suggested} |")
    lines += ["", "## 시드 변화"]
    if explore is not None:
        lines += [f"- 자동 키워드 추가: {', '.join(explore.keywords_added) or '없음'} / 퇴역: {', '.join(explore.keywords_retired) or '없음'}",
                  f"- 커뮤니티 자동 등록: {', '.join(explore.auto_communities) or '없음'}"]
    lines.append("- 후보 추가: " + (" · ".join(f"{n} {by[n].counts.get('candidates_added', 0)}" for n in ("search", "community") if n in by) or "없음"))
    lines += ["", "## 실패·경고"]
    warn = [f"- {r.name}: {r.error.splitlines()[0]}" for r in results if r.error and r.status != SKIPPED]
    warn += [f"- {r.name}: 건너뜀 ({r.error})" for r in results if r.status == SKIPPED and r.error]
    if "search" in by and by["search"].counts.get("bot_check"):
        warn.append("- search: Yahoo 봇 확인으로 조기 종료")
    if stale_reviews:
        warn.append(f"- {STALE_REVIEW_DAYS}일 넘게 판정 안 된 리뷰 도메인 {stale_reviews}개")
    if pruned:
        warn.append(f"- {KEEP_OUT_DAYS}일 지난 out 폴더 정리: {', '.join(pruned)}")
    lines += warn or ["- 없음"]
    return "\n".join(lines) + "\n"


# ---------- 실행기 ----------

class Runner:
    def __init__(self, settings: Settings, *, seeds_dir: Path, out_base: Path, today: str, only: list[str] | None = None,
                 skip: list[str] | None = None, budget_min: float = 90, dry_run: bool = False,
                 stages: dict[str, StageFn] | None = None, grace_sec: float = 5.0):
        self.settings = settings
        self.seeds_dir = Path(seeds_dir)
        self.out_base = Path(out_base)
        self.today = today
        self.out_dir = self.out_base / today
        self.wanted = [s for s in WORK_STAGES if (not only or s in only) and s not in (skip or [])]
        self.budget_sec = budget_min * 60
        self.dry_run = dry_run
        self.grace_sec = grace_sec
        self.stages = stages if stages is not None else self.default_stages()
        self.results: list[StageResult] = []
        self.explore_result: ExploreResult | None = None
        self.started = time.monotonic()

    # 단계 구현 -------------------------------------------------------------

    def default_stages(self) -> dict[str, StageFn]:
        return {"search": self.stage_search, "community": self.stage_community, "explore": self.stage_explore, "capture": self.stage_capture}

    def known(self) -> set[str]:
        return seed_domains(all_seed_files(self.seeds_dir))

    def search_keywords(self) -> tuple[list[str], list[str]]:
        manual = read_keywords(self.seeds_dir / "keywords.txt")
        state = load_state(self.seeds_dir / "explore_state.json")
        auto = pick_auto_keywords(state, read_keywords(self.seeds_dir / "keywords_auto.txt"), self.settings.nightly_search_auto)
        return manual, auto

    async def stage_search(self, budget: float) -> dict:
        manual, auto = self.search_keywords()
        tally = await discover_search_keywords(self.settings, manual + auto, self.seeds_dir / "candidates.csv", self.known(), stop_after_zero=2)
        state_path = self.seeds_dir / "explore_state.json"
        state = load_state(state_path)
        for kw, added in tally.added.items():
            record_run(state, kw, added, self.today, origin="manual" if kw in manual else "auto")
        if tally.bot_check:
            state["bot_check_date"] = self.today
        save_state(state_path, state)
        return {"keywords": len(tally.added), "auto_keywords": auto, "candidates_added": tally.total_added, "bot_check": tally.bot_check}

    async def stage_community(self, budget: float) -> dict:
        n = await discover_community(self.settings, self.seeds_dir / "community_lists.csv", self.seeds_dir / "candidates.csv", self.known())
        return {"communities": len(read_seeds(self.seeds_dir / "community_lists.csv")), "candidates_added": n}

    async def stage_explore(self, budget: float) -> dict:
        res = await run_explore(self.settings, seeds_dir=self.seeds_dir, out_dir=self.out_dir, today=self.today, budget_sec=max(1.0, budget - 60))
        self.explore_result = res
        return {"precaptured": res.precaptured, "auto_communities": res.auto_communities, "keywords_added": res.keywords_added,
                "keywords_retired": res.keywords_retired, "timed_out": res.timed_out,
                **{k: res.capture_summary.get(k, 0) for k in ("ok", "duplicate", "blocked_kr", "challenge", "error")}}

    async def stage_capture(self, budget: float) -> dict:
        deadline = time.monotonic() + budget
        counts: dict = {"labels": {}, "timed_out": False}
        blocklist = load_blocklist(self.seeds_dir / "blocklist.txt")
        for label in LABELS:
            remaining = deadline - time.monotonic()
            if remaining < 60:
                counts["labels"][label] = {"status": "skipped(budget)"}
                counts["timed_out"] = True
                continue
            seeds = [s for s in read_seeds(self.seeds_dir / f"{label}.csv") if registrable_domain(s.url) not in blocklist]
            s = replace(self.settings, click_menus=(label == "gambling"), refresh=False)
            try:
                summary = await asyncio.wait_for(
                    run_capture(s, seeds, label=label, emit_candidates=(label == "embedded_banner"),
                                candidates_path=self.seeds_dir / "candidates.csv", known_domains=frozenset(self.known())),
                    timeout=remaining)
                counts["labels"][label] = {"status": "ok", **summary}
            except asyncio.TimeoutError:
                counts["labels"][label] = {"status": "timeout"}
                counts["timed_out"] = True
        return counts

    # 실행 ------------------------------------------------------------------

    def budget_for(self, name: str) -> float:
        per = self.settings.nightly_budget_min.get(name, 10) * 60
        remaining = self.budget_sec - (time.monotonic() - self.started)
        return max(0.0, min(per, remaining))

    async def run_stage(self, name: str) -> StageResult:
        budget = self.budget_for(name)
        if budget <= 0:
            return StageResult(name, SKIPPED, 0.0, {}, BUDGET_EXHAUSTED)
        t0 = time.monotonic()
        try:
            counts = await asyncio.wait_for(self.stages[name](budget), timeout=budget + self.grace_sec)
            return StageResult(name, PARTIAL if counts.get("timed_out") else OK, time.monotonic() - t0, counts, None)
        except asyncio.TimeoutError:
            return StageResult(name, PARTIAL, time.monotonic() - t0, {}, f"예산 {budget / 60:.1f}분 초과")
        except Exception as e:   # 단계 격리: 어떤 예외도 다음 단계로 넘어간다
            return StageResult(name, FAILED, time.monotonic() - t0, {}, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}")

    def _log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with (self.out_dir / "run.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def exit_code(self) -> int:
        bad = any(r.status in (PARTIAL, FAILED) or (r.status == SKIPPED and r.error == BUDGET_EXHAUSTED) for r in self.results)
        return 1 if bad else 0

    async def run(self) -> int:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for name in WORK_STAGES:
            if name not in self.wanted:
                self.results.append(StageResult(name, SKIPPED, 0.0, {}, None))
                continue
            self._log(f"▶ {name}")
            r = await self.run_stage(name)
            self.results.append(r)
            self._log(f"■ {name} {r.status} {r.elapsed:.0f}s {_brief(r.counts)}" + (f" error={r.error.splitlines()[0]}" if r.error else ""))
        try:
            self.write_report()
        except Exception as e:
            self._log(f"보고서 실패: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            return 1
        return self.exit_code()

    def write_report(self) -> None:
        review_rows = self.explore_result.review_rows if self.explore_result else []
        thumbs = make_thumbs(review_rows, self.out_dir / "thumbs")
        daily = daily_counts(Store(self.settings.out_root, self.settings.salt).load_index(), self.today)
        stale = stale_review_count(Store(self.settings.review_root, self.settings.salt).load_index(), self.today, STALE_REVIEW_DAYS)
        pruned = prune_out(self.out_base, self.today, KEEP_OUT_DAYS)
        code = self.exit_code()
        (self.out_dir / "report.md").write_text(build_report(today=self.today, results=self.results, daily=daily, review_rows=review_rows, thumbs=thumbs,
                                                             explore=self.explore_result, stale_reviews=stale, pruned=pruned, exit_code=code), encoding="utf-8")
        (self.out_dir / "summary.json").write_text(json.dumps(
            {"date": self.today, "exit_code": code, "stages": [asdict(r) for r in self.results], "daily": daily, "review_pending": len(review_rows)},
            ensure_ascii=False, indent=1), encoding="utf-8")
        self._log(f"보고서: {self.out_dir / 'report.md'} (종료 코드 {code})")

    def dry_run_plan(self) -> str:
        manual, auto = self.search_keywords()
        cands = select_candidates(self.seeds_dir / "candidates.csv", self.settings.nightly_max_candidates, load_blocklist(self.seeds_dir / "blocklist.txt"))
        lines = [f"# dry-run {self.today} — 단계: {', '.join(self.wanted) or '없음'}",
                 f"search: 키워드 {len(manual) + len(auto)}개 (수동 {len(manual)} + 자동 {auto})",
                 f"community: 커뮤니티 페이지 {len(read_seeds(self.seeds_dir / 'community_lists.csv'))}개",
                 f"explore: 선캡처 후보 {len(cands)}개 → {self.settings.review_root}",
                 "capture: " + " · ".join(f"{lab} {len(read_seeds(self.seeds_dir / f'{lab}.csv'))}" for lab in LABELS) + f" 도메인 (recapture_days={self.settings.recapture_days})",
                 f"예산: 전체 {self.budget_sec / 60:.0f}분, 단계별 {self.settings.nightly_budget_min}"]
        return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_nightly.py -q`
Expected: 5 passed. (`test_runner_isolates_stages_and_writes_report` 의 explore 단계는 예산 0.6초 + 유예 0.1초 뒤 `partial` 이어야 한다.)

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/nightly.py tests/test_nightly.py
git commit -m "feat(crawler): nightly runner — isolated budgeted stages, lock, report, thumbnails, pruning

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: CLI — `nightly` · `explore` · `promote` 명령, `stats --review`, `capture --recapture-days`

**Files:**
- Modify: `src/crawler/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `nightly.Runner / acquire_lock / release_lock`, `explore.run_explore`, `promote.run_promote`, `seeds.all_seed_files`
- Produces: `python -m crawler nightly|explore|promote|stats --review|capture --recapture-days N`, `today_kst() -> str`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_cli.py` 끝에 추가

```python
def test_nightly_args_defaults():
    ns = build_parser().parse_args(["nightly"])
    assert ns.command == "nightly" and ns.date is None and ns.out_dir == "out" and ns.only is None and ns.skip is None
    assert ns.budget_min == 90 and ns.recapture_days == 1 and ns.max_candidates is None and ns.dry_run is False


def test_nightly_args_only_skip_lists():
    ns = build_parser().parse_args(["nightly", "--only", "search,explore", "--skip", "capture", "--budget-min", "30", "--date", "2026-10-20", "--dry-run"])
    assert ns.only == ["search", "explore"] and ns.skip == ["capture"] and ns.budget_min == 30 and ns.date == "2026-10-20" and ns.dry_run is True


def test_explore_and_promote_args():
    ns = build_parser().parse_args(["explore", "--max-candidates", "5", "--per-domain", "1"])
    assert ns.command == "explore" and ns.max_candidates == 5 and ns.per_domain == 1 and ns.out_dir == "out"
    ns2 = build_parser().parse_args(["promote", "out/2026-10-20/review.csv", "--dry-run"])
    assert ns2.command == "promote" and ns2.review_csv == "out/2026-10-20/review.csv" and ns2.dry_run is True


def test_stats_review_and_capture_recapture_days():
    assert build_parser().parse_args(["stats", "--review"]).review is True
    assert build_parser().parse_args(["stats"]).review is False
    assert build_parser().parse_args(["capture", "--label", "normal", "--seeds", "s.csv", "--recapture-days", "1"]).recapture_days == 1
    assert build_parser().parse_args(["capture", "--label", "normal", "--seeds", "s.csv"]).recapture_days is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_cli.py -q`
Expected: FAIL — `argparse.ArgumentError`/`SystemExit: 2` (알 수 없는 명령).

- [ ] **Step 3: `__main__.py` 전체를 아래로 바꾼다**

```python
"""CLI: python -m crawler discover|capture|stats|nightly|explore|promote"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import LABELS, load_settings
from .domains import registrable_domain
from .seeds import all_seed_files, load_blocklist, read_seeds, seed_domains
from .stats import format_table, summarize
from .store import Store, now_kst

SEEDS_DIR = Path("seeds")
ALL_SEED_FILES = all_seed_files(SEEDS_DIR)
STAGE_CHOICES = ("search", "community", "explore", "capture")


def today_kst() -> str:
    return now_kst().date().isoformat()


def _stage_list(text: str) -> list[str]:
    out = [s.strip() for s in text.split(",") if s.strip()]
    bad = [s for s in out if s not in STAGE_CHOICES]
    if bad:
        raise argparse.ArgumentTypeError(f"알 수 없는 단계 {bad}. 가능: {', '.join(STAGE_CHOICES)}")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crawler", description="도박 화면 데이터셋 수집기")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="시드 후보 수집 → seeds/candidates.csv")
    dk = d.add_subparsers(dest="kind", required=True)
    dc = dk.add_parser("community", help="검증 커뮤니티 페이지의 외부 링크 수집")
    dc.add_argument("--seeds", default=str(SEEDS_DIR / "community_lists.csv"))
    dc.add_argument("--out", default=str(SEEDS_DIR / "candidates.csv"))
    ds = dk.add_parser("search", help="Yahoo 검색 결과 수집")
    ds.add_argument("--keywords", default=str(SEEDS_DIR / "keywords.txt"))
    ds.add_argument("--per-keyword", type=int, default=20)
    ds.add_argument("--out", default=str(SEEDS_DIR / "candidates.csv"))

    c = sub.add_parser("capture", help="시드 파일의 도메인을 캡처")
    c.add_argument("--label", required=True, choices=LABELS)
    c.add_argument("--seeds", required=True)
    c.add_argument("--out", default=None, help="저장 루트 (기본: .env CRAWLER_OUT 또는 /Users/seongmin/datasets/gambling)")
    c.add_argument("--per-domain", type=int, default=None)
    c.add_argument("--max-domains", type=int, default=None)
    c.add_argument("--concurrency", type=int, default=None)
    c.add_argument("--emit-candidates", action="store_true", help="배너의 외부 링크 도메인을 seeds/candidates.csv에 추가")
    c.add_argument("--refresh", action="store_true", help="이미 수집한 도메인도 홈을 다시 열어 충전·가입 등 내부 페이지를 추가 수집")
    c.add_argument("--click-menus", action="store_true", help="홈의 충전·입금·가입 메뉴(버튼·JS 링크)를 클릭해 결제 직전 화면을 추가 수집")
    c.add_argument("--max-menu-clicks", type=int, default=None, help="도메인당 클릭할 메뉴 수 (기본 2)")
    c.add_argument("--recapture-days", type=int, default=None, help="이 일수 안에 찍은 화면은 다시 찍지 않는다 (기본 7, 야간 루프 1)")

    s = sub.add_parser("stats", help="라벨별 수집 현황")
    s.add_argument("--out", default=None)
    s.add_argument("--review", action="store_true", help="본 데이터셋 대신 리뷰 루트(_review)를 집계")

    n = sub.add_parser("nightly", help="야간 루프: search → community → explore → capture → 보고서")
    n.add_argument("--date", default=None, help="YYYY-MM-DD (기본 오늘 KST)")
    n.add_argument("--out-dir", default="out", help="보고서 루트 (out/<날짜>/)")
    n.add_argument("--only", type=_stage_list, default=None, help="이 단계만 (쉼표 구분)")
    n.add_argument("--skip", type=_stage_list, default=None, help="이 단계는 건너뜀 (쉼표 구분)")
    n.add_argument("--budget-min", type=int, default=90, help="전체 예산(분)")
    n.add_argument("--recapture-days", type=int, default=1)
    n.add_argument("--max-candidates", type=int, default=None, help="선캡처 후보 상한 (기본 40)")
    n.add_argument("--dry-run", action="store_true", help="계획만 출력")

    e = sub.add_parser("explore", help="후보 선캡처 + review.csv + 키워드 확장만 실행")
    e.add_argument("--date", default=None)
    e.add_argument("--out-dir", default="out")
    e.add_argument("--max-candidates", type=int, default=None)
    e.add_argument("--per-domain", type=int, default=None, help="후보 도메인당 페이지 수 (기본 2)")

    pr = sub.add_parser("promote", help="review.csv 의 verdict 를 시드·데이터셋에 반영")
    pr.add_argument("review_csv")
    pr.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.command == "stats":
        settings = load_settings(out=ns.out)
        root = settings.review_root if ns.review else settings.out_root
        print(format_table(summarize(Store(root, settings.salt).load_index())))
        return 0
    if ns.command == "discover":
        from .discover import discover_community, discover_search  # playwright import 지연
        settings = load_settings()
        known = seed_domains(ALL_SEED_FILES)
        if ns.kind == "community":
            n = asyncio.run(discover_community(settings, Path(ns.seeds), Path(ns.out), known))
        else:
            n = asyncio.run(discover_search(settings, Path(ns.keywords), Path(ns.out), known, ns.per_keyword))
        print(f"후보 {n}개 추가 → {ns.out}. 검토 후 seeds/gambling.csv로 옮기세요.")
        return 0
    if ns.command == "nightly":
        from .nightly import Runner, acquire_lock, release_lock
        settings = load_settings(recapture_days=ns.recapture_days, nightly_max_candidates=ns.max_candidates)
        today = ns.date or today_kst()
        runner = Runner(settings, seeds_dir=SEEDS_DIR, out_base=Path(ns.out_dir), today=today, only=ns.only, skip=ns.skip,
                        budget_min=ns.budget_min, dry_run=ns.dry_run)
        if ns.dry_run:
            print(runner.dry_run_plan())
            return 0
        lock = Path(ns.out_dir) / ".lock"
        if not acquire_lock(lock):
            print(f"이미 실행 중입니다: {lock}")
            return 2
        try:
            return asyncio.run(runner.run())
        finally:
            release_lock(lock)
    if ns.command == "explore":
        from .explore import run_explore
        settings = load_settings(nightly_candidate_pages=ns.per_domain)
        today = ns.date or today_kst()
        res = asyncio.run(run_explore(settings, seeds_dir=SEEDS_DIR, out_dir=Path(ns.out_dir) / today, today=today, max_candidates=ns.max_candidates))
        print(json.dumps({"precaptured": res.precaptured, "auto_communities": res.auto_communities, "keywords_added": res.keywords_added,
                          "keywords_retired": res.keywords_retired, "review_csv": str(res.review_csv), **res.capture_summary}, ensure_ascii=False, indent=2))
        return 0
    if ns.command == "promote":
        from .promote import run_promote
        return run_promote(Path(ns.review_csv), load_settings(), SEEDS_DIR, today=today_kst(), dry_run=ns.dry_run)
    # capture
    from .capture import run_capture  # playwright import 지연
    settings = load_settings(out=ns.out, per_domain=ns.per_domain, max_domains=ns.max_domains, concurrency=ns.concurrency, refresh=ns.refresh or None,
                             click_menus=ns.click_menus or None, max_menu_clicks=ns.max_menu_clicks, recapture_days=ns.recapture_days)
    blocklist = load_blocklist(SEEDS_DIR / "blocklist.txt")
    seeds = [s for s in read_seeds(Path(ns.seeds)) if registrable_domain(s.url) not in blocklist]
    if not seeds:
        print(f"시드가 없습니다: {ns.seeds}")
        return 1
    print(f"[{ns.label}] 도메인 {len(seeds)}개, 저장 루트 {settings.out_root}")
    summary = asyncio.run(run_capture(settings, seeds, label=ns.label, emit_candidates=ns.emit_candidates,
                                      candidates_path=SEEDS_DIR / "candidates.csv",
                                      known_domains=frozenset(seed_domains(ALL_SEED_FILES))))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인 + 실제 dry-run**

Run: `.venv/bin/pytest -q` → 전부 PASS.
Run: `.venv/bin/python -m crawler nightly --dry-run` → 아래 비슷한 출력(수치는 그날 시드 기준). 예외가 나면 안 된다.

```
# dry-run 2026-10-xx — 단계: search, community, explore, capture
search: 키워드 10개 (수동 10 + 자동 [])
community: 커뮤니티 페이지 32개
explore: 선캡처 후보 4개 → /Users/seongmin/datasets/gambling/_review
capture: gambling 55 · embedded_banner 21 · hard_negative 23 · normal 8 도메인 (recapture_days=1)
예산: 전체 90분, 단계별 {'search': 12, 'community': 8, 'explore': 25, 'capture': 40}
```

Run: `.venv/bin/python -m crawler stats --review` → 헤더 2줄과 `(index.jsonl 없음 또는 비어 있음)`.

- [ ] **Step 5: 커밋**

```bash
git add src/crawler/__main__.py tests/test_cli.py
git commit -m "feat(crawler): nightly, explore and promote commands; stats --review; capture --recapture-days

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: 운영 — nightly.sh, launchd plist, 문서, 실연 테스트

**Files:**
- Create: `scripts/nightly.sh`, `scripts/launchd/com.gambling-crawler.nightly.plist`, `scripts/README.md`
- Modify: `seeds/README.md`, `docs/superpowers/specs/2026-10-19-nightly-seed-exploration-design.md` (7절 `review_dir` 표기)

**Interfaces:**
- Consumes: `python -m crawler nightly` 종료 코드 0/1/2

- [ ] **Step 1: `scripts/nightly.sh`**

```zsh
#!/bin/zsh
# launchd 진입점. 저장소로 이동해 야간 루프를 돌리고 로그를 out/launchd.log 에 덧붙인다. 종료 코드는 crawler nightly 의 것을 그대로 돌려준다.
set -u
cd "$(dirname "$0")/.." || exit 2
mkdir -p out
echo "[$(date '+%F %T')] nightly.sh 시작 ($*)" >> out/launchd.log
caffeinate -i .venv/bin/python -m crawler nightly "$@" >> out/launchd.log 2>&1
rc=$?
echo "[$(date '+%F %T')] nightly.sh 종료 rc=$rc" >> out/launchd.log
exit $rc
```

`chmod +x scripts/nightly.sh`.

- [ ] **Step 2: `scripts/launchd/com.gambling-crawler.nightly.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.gambling-crawler.nightly</string>
  <key>ProgramArguments</key><array><string>/bin/zsh</string><string>-lc</string><string>/Users/seongmin/gambling-content-detection/scripts/nightly.sh</string></array>
  <key>WorkingDirectory</key><string>/Users/seongmin/gambling-content-detection</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/seongmin/gambling-content-detection/out/launchd.log</string>
  <key>StandardErrorPath</key><string>/Users/seongmin/gambling-content-detection/out/launchd.log</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/local/bin:/usr/bin:/bin</string><key>LANG</key><string>ko_KR.UTF-8</string></dict>
</dict></plist>
```

- [ ] **Step 3: `scripts/README.md`**

```markdown
# 야간 루프 운영

매일 04:30 `python -m crawler nightly` 가 search → community → explore → capture 를 돌리고 `out/<날짜>/report.md` 를 쓴다. 설계는 `docs/superpowers/specs/2026-10-19-nightly-seed-exploration-design.md`.

## 설치·해제
```bash
cp scripts/launchd/com.gambling-crawler.nightly.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gambling-crawler.nightly.plist
launchctl kickstart -k gui/$(id -u)/com.gambling-crawler.nightly   # 지금 한 번 실행(검증용)
launchctl bootout gui/$(id -u)/com.gambling-crawler.nightly         # 해제
```
전제: 전원 연결, 잠자기 방지(또는 `sudo pmset repeat wake MTWRFSU 04:25:00`), 가정용 ISP(차단은 `blocked_kr` 로 기록되는 것이 정상). 회사 앱 루프(02:00, 최대 150분)와 겹치지 않게 04:30.

## 아침 루틴
1. `out/<날짜>/report.md` 를 연다. 맨 위 요약 3줄과 "실패·경고" 를 본다.
2. "검토 대기" 표의 썸네일을 보며 `out/<날짜>/review.csv` 의 `verdict` 열을 채운다: `gambling` · `embedded_banner` · `hard_negative` · `normal` · `community` · `exclude` · `blocked`. 비우면 다음에 다시 판단.
3. `.venv/bin/python -m crawler promote out/<날짜>/review.csv --dry-run` 으로 계획을 보고, 맞으면 `--dry-run` 없이 실행한다. 두 번 돌려도 안전하다.
4. 시드 변경(`seeds/*.csv`, `keywords_auto.txt`, `explore_state.json`)은 루프가 커밋하지 않는다. 확인 후 직접 커밋한다.

## 수동 실행
- 전체: `.venv/bin/python -m crawler nightly` (`--dry-run` 으로 계획만, `--only explore` 처럼 단계 선택, `--budget-min 30`)
- 선캡처만: `.venv/bin/python -m crawler explore --max-candidates 10`
- 리뷰 루트 현황: `.venv/bin/python -m crawler stats --review`
- 잠금이 남아 실행이 거부되면(`out/.lock`): 살아 있는 프로세스가 없을 때만 지운다.

## 종료 코드
0 정상 · 1 일부 단계 실패/부분(보고서의 실패 섹션 확인) · 2 실행 불가(`.env`/CRAWLER_SALT 없음, 잠금, 저장 루트 쓰기 불가)
```

- [ ] **Step 4: `seeds/README.md` 의 "실행 순서" 아래에 절을 추가**

```markdown
## 야간 루프가 바꾸는 파일

- `candidates.csv`: discover 가 `unverified` 로 추가하고, 선캡처하면 note 를 `review: <날짜>` 로, `promote` 가 판정 결과(`→ gambling.csv (review <날짜>)`, `excluded: …`, `blocked_kr <날짜>`)로 바꾼다.
- `community_lists.csv`: 선캡처 페이지가 커뮤니티로 보이면 `source=auto:<날짜>`, `note=자동 등록(미검토)` 로 추가된다. `exclude` 판정이면 지워진다.
- `keywords_auto.txt`, `explore_state.json`: 자동 키워드와 수확 기록. 손으로 고칠 키워드는 `keywords.txt` 에만.
- 라벨 시드 4개: `promote` 가 `source=review:<날짜>` 로 추가한다.
```

- [ ] **Step 5: 스펙 7절 `review_dir` 설명을 실제와 맞춘다**

`docs/superpowers/specs/2026-10-19-nightly-seed-exploration-design.md` 7절의 "`review_dir` 은 `_review/candidate/<해시>` 상대 경로." 를 "`review_dir` 은 리뷰 폴더의 절대 경로(`<리뷰 루트>/candidate/<해시>`). 리뷰 루트가 `CRAWLER_REVIEW` 로 바뀌어도 그대로 쓰기 위해서다." 로 바꾼다.

- [ ] **Step 6: 실연 — 단계 하나를 실제로 돌려 본다 (네트워크 사용, 5분 안팎)**

Run: `.venv/bin/python -m crawler nightly --only explore --max-candidates 2 --budget-min 10`
Expected: 종료 코드 0 또는 1. `out/<오늘>/report.md`·`review.csv`·`summary.json`·`run.log` 가 생기고, 보고서 "검토 대기" 표에 썸네일이 보인다(후보가 차단·오류면 썸네일 없이 상태만). `seeds/candidates.csv` 의 해당 행 note 가 `review: <오늘>` 로 바뀐다. `.venv/bin/python -m crawler stats --review` 에 `candidate` 행이 나온다.
그다음: `.venv/bin/python -m crawler promote out/<오늘>/review.csv --dry-run` 이 행마다 `[skip]` 을 출력한다(판정 비어 있음).

실연 결과를 커밋 메시지 본문에 한 줄로 적는다(예: "실연: explore 2후보 → ok 1·blocked_kr 1").

- [ ] **Step 7: 전체 테스트 + 커밋**

Run: `.venv/bin/pytest -q` → 전부 PASS.

```bash
git add scripts/nightly.sh scripts/launchd/com.gambling-crawler.nightly.plist scripts/README.md seeds/README.md docs/superpowers/specs/2026-10-19-nightly-seed-exploration-design.md seeds/candidates.csv seeds/keywords_auto.txt seeds/explore_state.json
git commit -m "chore(crawler): nightly launchd entry point, operations docs; seeds touched by the first explore run

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

(`seeds/community_lists.csv` 가 실연에서 바뀌었으면 함께 add 한다. `out/` 은 gitignore 라 올라가지 않는다.)

- [ ] **Step 8: launchd 등록은 사람이 한다**

이 계획은 plist 설치를 실행하지 않는다. `scripts/README.md` 의 설치 명령을 사용자에게 안내하고, 첫 자동 실행 다음 날 아침 `out/launchd.log` 와 `out/<날짜>/report.md` 를 확인하도록 한다.

---

## 자가 검토 메모

- 스펙 커버리지: 4절 명령(nightly·explore·promote·stats --review·capture --recapture-days) → Task 11; 5.1 검색 회전·봇 확인 → Task 7·10; 5.2 → Task 10; 5.3 선캡처·커뮤니티 자동 등록·review.csv·note 갱신·키워드 확장 → Task 5·6·8; 5.4 재캡처(`recapture_days=1`, `skip_blocked_days=7`, 라벨별 예산 skip) → Task 4·10; 5.5·8절 보고서(요약 3줄·단계 표·전일 대비·검토 대기 썸네일·시드 변화·실패 경고·30일 정리) → Task 10; 6절 신호·추천 → Task 6; 7절 판정 처리 7종·거부·재실행 안전·auto 커뮤니티 되돌리기·중복 줄 금지 → Task 9; 9절 저장 규격(`_review`, `CRAWLER_REVIEW`, meta 필드, keywords_auto·state, out 구조, `.lock`) → Task 1·3·4·5·10; 10절 재캡처 정책 → Task 3·4; 11절 격리·예산·잠금·종료 코드 → Task 10·11; 12절 테스트 → 각 Task; 13절 운영 → Task 12.
- 스펙과 다른 점 1곳: `review_dir` 을 상대 경로가 아니라 절대 경로로 둔다(Task 12 Step 5 에서 스펙을 고친다).
- 기존 동작 변화: `ok_count` 가 `recapture_days` 창으로 세므로, 수동 `capture` 도 7일이 지난 도메인은 다시 연다(이전엔 전체 기간 누적). 선행 스펙의 "재실행 판단" 과 같은 의도이며 테스트 `test_rerun_skips_domain_that_reached_per_domain` 은 같은 날 재실행이라 그대로 통과한다.
