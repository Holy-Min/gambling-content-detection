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


async def test_run_explore_budget_already_spent_skips_capture_but_writes_review(site, tmp_path):
    settings = fast_settings(tmp_path)
    sd = make_seeds(tmp_path, [cand(site + "/")])
    out = tmp_path / "out" / "t"
    res = await run_explore(settings, seeds_dir=sd, out_dir=out, today="2026-10-20", budget_sec=0.0)
    assert res.timed_out is True and res.capture_summary["skipped_deadline"] == 1 and res.capture_summary["ok"] == 0
    assert res.precaptured == 0 and res.review_rows == [] and (out / "review.csv").exists()
    assert read_rows(sd / "candidates.csv")[0]["note"] == "unverified"   # 마감에 못 간 후보는 다음 밤에 다시 고른다
