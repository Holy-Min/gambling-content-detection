"""시드 탐색: 후보 선캡처(리뷰 루트) → 신호·추천 → 커뮤니티 자동 등록 → review.csv → candidates note 갱신 → 키워드 확장."""
from __future__ import annotations

import time
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
    """후보를 candidate 라벨로 리뷰 루트에 캡처한다. 예산은 협조적 마감(deadline)으로 건다 — Playwright 기동 중 태스크를 취소하면
    이벤트 루프가 멈추므로 asyncio.wait_for 를 쓰지 않는다. (요약, 마감에 걸렸는지). 마감에 걸려도 그때까지의 행은 store 에 남아 있다."""
    deadline = None if budget_sec is None else time.monotonic() + budget_sec
    summary = await run_capture(candidate_settings(settings), seeds, label=CANDIDATE_LABEL, store=store, deadline=deadline)
    return summary, bool(summary.get("skipped_deadline") or summary.get("deadline_hit"))

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
    write_review_csv(res.review_csv, res.review_rows, merge=True)
    update_notes(candidates_csv, {r.domain: f"review: {today}" for r in res.review_rows})
    res.keywords_added, res.keywords_retired = expand_keywords(
        settings, seeds_dir, Store(settings.out_root, settings.salt), [r.title for r in res.review_rows if r.status == "ok"])
    return res
