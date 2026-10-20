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


def _two_label_setup(tmp_path):
    settings = settings_for(tmp_path)
    sd = make_seeds(tmp_path, ["a.com", "b.com"])
    dirs = {d: make_review(settings, d) for d in ("a.com", "b.com")}
    csv_path = tmp_path / "review.csv"
    write_review_csv(csv_path, [rr("a.com", "gambling", dirs["a.com"]), rr("b.com", "gambling", dirs["b.com"])])
    return settings, sd, dirs, csv_path


def test_promote_mid_run_failure_keeps_progress_and_rerun_finishes(tmp_path, monkeypatch):
    settings, sd, dirs, csv_path = _two_label_setup(tmp_path)
    real = Store.adopt_domain
    calls = []

    def flaky(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Store, "adopt_domain", flaky)
    try:
        run_promote(csv_path, settings, sd, today="2026-10-20")
        raise AssertionError("expected failure")
    except RuntimeError:
        pass
    review = Store(settings.review_root, settings.salt)
    notes = {c["url"]: c["note"] for c in read_rows(sd / "candidates.csv")}
    assert notes["https://a.com/"] == "→ gambling.csv (review 2026-10-20)" and notes["https://b.com/"] == "review: 2026-10-20"
    assert review.rows_for("candidate", "a.com") == [] and review.rows_for("candidate", "b.com") != []
    monkeypatch.setattr(Store, "adopt_domain", real)
    assert run_promote(csv_path, settings, sd, today="2026-10-20") == 0
    main = Store(settings.out_root, settings.salt)
    assert main.ok_count("gambling", "b.com") == 2 and main.ok_count("gambling", "a.com") == 2
    review = Store(settings.review_root, settings.salt)   # 디스크에서 다시 읽음
    assert review.rows_for("candidate", "a.com") == [] and review.rows_for("candidate", "b.com") == []
    notes = {c["url"]: c["note"] for c in read_rows(sd / "candidates.csv")}
    assert notes["https://b.com/"] == "→ gambling.csv (review 2026-10-20)"


def test_promote_done_row_cleans_leftover_rows_and_note(tmp_path):
    import shutil
    settings, sd, dirs, csv_path = _two_label_setup(tmp_path)
    shutil.rmtree(dirs["a.com"])   # 폴더만 사라지고 색인 행은 남은 상태
    review = Store(settings.review_root, settings.salt)
    assert review.rows_for("candidate", "a.com") != []
    assert run_promote(csv_path, settings, sd, today="2026-10-20") == 0
    review = Store(settings.review_root, settings.salt)   # 디스크에서 다시 읽음
    assert review.rows_for("candidate", "a.com") == []
    notes = {c["url"]: c["note"] for c in read_rows(sd / "candidates.csv")}
    assert notes["https://a.com/"] == "→ gambling.csv (review 2026-10-20)"


def test_promote_label_verdict_without_rows_keeps_folder(tmp_path, capsys):
    settings = settings_for(tmp_path)
    sd = make_seeds(tmp_path, ["g.com"])
    d = tmp_path / "review_dir_only"; d.mkdir(); (d / "x.png").write_bytes(b"png")
    csv_path = tmp_path / "review.csv"
    write_review_csv(csv_path, [rr("g.com", "gambling", str(d))])
    assert run_promote(csv_path, settings, sd, today="2026-10-20") == 0
    assert d.exists() and (d / "x.png").exists()
    assert "[promote] g.com: 리뷰 행이 없어 폴더를 그대로 둠" in capsys.readouterr().out
    assert read_rows(sd / "gambling.csv")[0]["url"] == "https://g.com/"
    assert {c["url"]: c["note"] for c in read_rows(sd / "candidates.csv")}["https://g.com/"] == "→ gambling.csv (review 2026-10-20)"


def test_promote_removes_auto_community_row_for_non_community_verdicts(tmp_path):
    settings = settings_for(tmp_path)
    sd = make_seeds(tmp_path, ["autocomm.com", "autoex.com", "manual.com"])
    write_rows(sd / "community_lists.csv", [
        {"url": "https://autocomm.com/", "source": "auto:2026-10-20", "added_at": "2026-10-20", "note": "자동"},
        {"url": "https://autoex.com/", "source": "auto:2026-10-20", "added_at": "2026-10-20", "note": "자동"},
        {"url": "https://manual.com/", "source": "review:2026-10-01", "added_at": "2026-10-01", "note": "사람"}])
    dirs = {d: make_review(settings, d) for d in ("autocomm.com", "autoex.com", "manual.com")}
    csv_path = tmp_path / "review.csv"
    write_review_csv(csv_path, [rr("autocomm.com", "gambling", dirs["autocomm.com"]), rr("autoex.com", "blocked", dirs["autoex.com"]),
                                rr("manual.com", "gambling", dirs["manual.com"])])
    assert run_promote(csv_path, settings, sd, today="2026-10-20") == 0
    assert [c["url"] for c in read_rows(sd / "community_lists.csv")] == ["https://manual.com/"]   # 사람이 넣은 행은 유지
