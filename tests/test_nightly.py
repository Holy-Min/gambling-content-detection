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
