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


def test_keywords_to_record_drops_trailing_zero_streak_on_bot_check():
    from crawler.discover import SearchTally
    from crawler.nightly import keywords_to_record
    t = SearchTally(stop_after=2)
    for kw, n in (("a", 10), ("b", 0), ("c", 5), ("d", 0), ("e", 0)):
        t.add(kw, links=n, added=0)
    assert t.bot_check and keywords_to_record(t) == ["a", "b", "c"]
    ok = SearchTally(stop_after=2)
    ok.add("x", links=0, added=0); ok.add("y", links=3, added=1)
    assert keywords_to_record(ok) == ["x", "y"]


def test_cell_escapes_pipe_and_html_chars():
    from crawler.nightly import _cell
    assert _cell("a|<b>`c`") == "a\\|&lt;b&gt;\\`c\\`"


# ---------- 정상 쪽 탐색 경로 ----------

def _normal_runner(tmp_path, *, normal_kws=None, **kw):
    seeds = tmp_path / "seeds"
    seeds.mkdir(exist_ok=True)
    (seeds / "keywords.txt").write_text("도박키워드\n", encoding="utf-8")
    if normal_kws is not None:
        (seeds / "keywords_normal.txt").write_text("# 주석\n" + "\n".join(normal_kws) + "\n", encoding="utf-8")
    return Runner(tiny_settings(tmp_path), seeds_dir=seeds, out_base=tmp_path / "out", today="2026-11-11", **kw)


def _fake_search(calls, *, gambling_bot=False, gambling_timeout=False, normal_bot=False, normal_run=None):
    from crawler.discover import SearchTally

    async def fake(settings, keywords, out_csv, known, per_keyword=20, stop_after_zero=2, deadline=None, track="gambling"):
        calls.append((track, list(keywords)))
        t = SearchTally(stop_after=2)
        if track == "normal":
            for k in (keywords if normal_run is None else keywords[:normal_run]):
                t.add(k, links=0 if normal_bot else 3, added=0 if normal_bot else 1)
            t.bot_check = normal_bot
            t.timed_out = normal_run is not None
        else:
            for k in keywords:
                t.add(k, links=3, added=2)
            t.bot_check, t.timed_out = gambling_bot, gambling_timeout
        return t
    return fake


def test_normal_keywords_rotation(tmp_path):
    from crawler.keywords import load_state, record_run, save_state
    kws = [f"k{i}" for i in range(15)]
    r = _normal_runner(tmp_path, normal_kws=kws)
    assert r.normal_keywords() == kws[:5]
    state = load_state(r.seeds_dir / "explore_state.json")
    for k in kws[:5]:
        record_run(state, k, 1, "2026-11-10", origin="normal")
    save_state(r.seeds_dir / "explore_state.json", state)
    assert r.normal_keywords() == kws[5:10]


async def test_normal_keywords_missing_file(tmp_path, monkeypatch):
    import crawler.nightly as nm
    calls = []
    monkeypatch.setattr(nm, "discover_search_keywords", _fake_search(calls))
    r = _normal_runner(tmp_path)
    assert r.normal_keywords() == []
    res = await r.stage_search(10)
    assert [c[0] for c in calls] == ["gambling"]
    assert res["normal_keywords"] == [] and res["normal_candidates_added"] == 0 and res["normal_bot_check"] is False
    assert res["normal_timed_out"] is False
    assert res["candidates_added"] == 2 and res["bot_check"] is False
    (r.seeds_dir / "keywords_normal.txt").write_text("# 주석만\n", encoding="utf-8")
    assert r.normal_keywords() == []


async def test_stage_search_runs_normal_after_gambling(tmp_path, monkeypatch):
    import crawler.nightly as nm
    from crawler.keywords import load_state
    calls = []
    monkeypatch.setattr(nm, "discover_search_keywords", _fake_search(calls))
    r = _normal_runner(tmp_path, normal_kws=[f"n{i}" for i in range(8)])
    res = await r.stage_search(10)
    assert [c[0] for c in calls] == ["gambling", "normal"]
    assert calls[1][1] == [f"n{i}" for i in range(5)]
    assert res["normal_keywords"] == calls[1][1] and res["normal_candidates_added"] == 5
    assert res["candidates_added"] == 2     # 도박 쪽 수치에 정상 쪽이 섞이지 않는다
    state = load_state(r.seeds_dir / "explore_state.json")
    assert state["keywords"]["n0"]["origin"] == "normal" and state["keywords"]["n0"]["last_run"] == "2026-11-11"
    assert state["keywords"]["도박키워드"]["origin"] == "manual"


async def test_stage_search_skips_normal_on_bot_check(tmp_path, monkeypatch):
    import crawler.nightly as nm
    for kwargs in ({"gambling_bot": True}, {"gambling_timeout": True}):
        calls = []
        monkeypatch.setattr(nm, "discover_search_keywords", _fake_search(calls, **kwargs))
        r = _normal_runner(tmp_path, normal_kws=["n0", "n1"])
        res = await r.stage_search(10)
        assert [c[0] for c in calls] == ["gambling"]
        assert res["normal_keywords"] == [] and res["normal_candidates_added"] == 0
        assert res["normal_timed_out"] is False


async def test_normal_bot_check_does_not_set_bot_check_date(tmp_path, monkeypatch):
    import crawler.nightly as nm
    from crawler.keywords import load_state
    calls = []
    monkeypatch.setattr(nm, "discover_search_keywords", _fake_search(calls, normal_bot=True))
    r = _normal_runner(tmp_path, normal_kws=["n0", "n1", "n2"])
    res = await r.stage_search(10)
    assert res["normal_bot_check"] is True and res["bot_check"] is False and res["candidates_added"] == 2
    assert load_state(r.seeds_dir / "explore_state.json")["bot_check_date"] is None


def test_normal_keywords_not_retired_by_expand(tmp_path):
    from crawler.keywords import expand, load_state, record_run
    state = load_state(tmp_path / "s.json")
    for _ in range(5):
        record_run(state, "n0", 0, "2026-11-11", origin="normal")
    _, _, retired = expand(state, ["a1"], [], add_per_day=0, pool=10, retire_streak=3)
    assert "n0" not in retired and not state["keywords"]["n0"].get("retired")


def test_dry_run_plan_shows_normal(tmp_path):
    r = _normal_runner(tmp_path, normal_kws=["n0", "n1"])
    plan = r.dry_run_plan()
    assert "정상 검색: 키워드 2개" in plan and "n0" in plan and "정상 후보 자리" in plan


def test_build_report_has_normal_lines():
    from crawler.nightly import StageResult, build_report
    from crawler.config import LABELS
    daily = {lab: {"ok": 0, "duplicate": 0, "blocked_kr": 0, "challenge": 0, "error": 0, "total_ok": 0} for lab in LABELS}
    results = [StageResult("search", "ok", counts={"candidates_added": 3, "normal_keywords": ["n0"], "normal_candidates_added": 4}),
               StageResult("explore", "ok", counts={"precaptured_normal": 6})]
    rep = build_report(today="2026-11-11", results=results, daily=daily, review_rows=[], thumbs={}, explore=None, stale_reviews=0, pruned=[], exit_code=0)
    assert "정상 쪽: 키워드 1개 (n0) · 추가 후보 4 · 미리 찍은 정상 후보 6" in rep


async def test_stage_search_normal_timed_out_reports_only_run_keywords(tmp_path, monkeypatch):
    import crawler.nightly as nm
    calls = []
    monkeypatch.setattr(nm, "discover_search_keywords", _fake_search(calls, normal_run=2))
    r = _normal_runner(tmp_path, normal_kws=[f"n{i}" for i in range(8)])
    res = await r.stage_search(10)
    assert calls[1][1] == [f"n{i}" for i in range(5)]
    assert res["normal_keywords"] == ["n0", "n1"]
    assert res["normal_timed_out"] is True and res["timed_out"] is False


def test_build_report_marks_normal_timed_out():
    from crawler.nightly import StageResult, build_report
    from crawler.config import LABELS
    daily = {lab: {"ok": 0, "duplicate": 0, "blocked_kr": 0, "challenge": 0, "error": 0, "total_ok": 0} for lab in LABELS}
    results = [StageResult("search", "ok", counts={"normal_keywords": ["n0"], "normal_timed_out": True})]
    rep = build_report(today="2026-11-11", results=results, daily=daily, review_rows=[], thumbs={}, explore=None, stale_reviews=0, pruned=[], exit_code=0)
    line = next(l for l in rep.splitlines() if l.startswith("- 정상 쪽:"))
    assert "마감으로 중단" in line
