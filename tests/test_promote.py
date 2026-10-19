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
