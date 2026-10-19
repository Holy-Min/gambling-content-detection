"""야간 루프 실행기: search → community → explore → capture 를 예산 안에서 격리 실행하고 보고서를 쓴다.
시간 예산은 단계 함수가 협조적으로 지키고(run_capture deadline 등), wait_for 는 안전망, 워치독이 최후 수단이다."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
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
                 stages: dict[str, StageFn] | None = None, grace_sec: float = 300.0, hard_kill_grace_sec: float = 900.0):
        self.settings = settings
        self.seeds_dir = Path(seeds_dir)
        self.out_base = Path(out_base)
        self.today = today
        self.out_dir = self.out_base / today
        self.wanted = [s for s in WORK_STAGES if (not only or s in only) and s not in (skip or [])]
        self.budget_sec = budget_min * 60
        self.dry_run = dry_run
        self.grace_sec = grace_sec                       # wait_for 안전망 유예(단계 함수가 스스로 마감을 지키므로 평소엔 안 걸린다)
        self.hard_kill_grace_sec = hard_kill_grace_sec   # 전체 예산 + 이 유예가 지나면 os._exit(3) — 취소가 멈춰도 프로세스는 끝난다
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
            # 취소(wait_for) 대신 협조적 마감: Playwright 기동 중 취소는 이벤트 루프를 멈춘다
            summary = await run_capture(s, seeds, label=label, emit_candidates=(label == "embedded_banner"),
                                        candidates_path=self.seeds_dir / "candidates.csv", known_domains=frozenset(self.known()),
                                        deadline=deadline)
            cut = bool(summary.get("skipped_deadline") or summary.get("deadline_hit"))
            counts["labels"][label] = {"status": "timeout" if cut else "ok", **summary}
            counts["timed_out"] = counts["timed_out"] or cut
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

    def _hard_exit(self) -> None:
        try:
            self._log(f"하드 타임아웃({(self.budget_sec + self.hard_kill_grace_sec) / 60:.0f}분): 프로세스를 강제 종료한다(종료 코드 3)")
        finally:
            os._exit(3)

    async def run(self) -> int:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        watchdog = threading.Timer(self.budget_sec + self.hard_kill_grace_sec, self._hard_exit)
        watchdog.daemon = True
        watchdog.start()
        try:
            return await self._run_stages()
        finally:
            watchdog.cancel()

    async def _run_stages(self) -> int:
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
