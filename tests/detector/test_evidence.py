from detector.evidence import domain_status, summarize, rotation_groups, open_share


def _r(domain, status, at, label="gambling", **kw):
    return {"domain": domain, "status": status, "captured_at": at, "label": label, **kw}


def test_domain_status_prefers_open():
    rows = [
        _r("a.com", "blocked_kr", "2026-09-30T10:00:00+09:00"),
        _r("a.com", "ok", "2026-10-07T10:00:00+09:00"),
        _r("b.com", "blocked_kr", "2026-09-30T10:00:00+09:00"),
        _r("c.com", "ok", "2026-10-01T10:00:00+09:00", label="normal"),
    ]
    st = domain_status(rows)
    assert st == {"a.com": "open", "b.com": "blocked_kr"}


def test_open_share_excludes_challenge():
    counts = {"open": 3, "blocked_kr": 1, "challenge": 2, "error": 0}
    assert open_share(counts) == 0.75


def test_rotation_groups():
    groups, doms = rotation_groups(["toto12.com", "toto34.net", "abc.com"])
    assert (groups, doms) == (1, 2)


def test_summarize_small(tmp_path):
    import json
    rows = [
        _r("toto1.com", "ok", "2026-10-01T00:00:00+09:00", final_url="https://other.com/", seed_source="banner:x.com"),
        _r("toto2.net", "blocked_kr", "2026-10-01T00:00:00+09:00", seed_source="review:2026-10-20"),
        _r("w.com", "ok", "2026-10-01T00:00:00+09:00", label="embedded_banner",
           banners=[{"external": True}, {"external": False}, {"external": True}]),
    ]
    idx = tmp_path / "i.jsonl"
    idx.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    sd = tmp_path / "seeds"
    sd.mkdir()
    h = "url,source,added_at,note\n"
    (sd / "embedded_banner.csv").write_text(h + "https://w.com/,x,2026-10-01,\n", encoding="utf-8")
    (sd / "gambling.csv").write_text(h + "https://toto2.net/,review:2026-10-20,2026-10-20,\n", encoding="utf-8")
    (sd / "candidates.csv").write_text(h + "https://toto2.net/,banner:w.com,2026-10-01,review\n", encoding="utf-8")
    s = summarize(idx, sd)
    assert s["gambling_domains_total"] == 2
    assert s["status_counts"]["open"] == 1 and s["status_counts"]["blocked_kr"] == 1
    assert s["open_share"] == 0.5
    assert s["embedded_seeds"] == 1 and s["banner_links"] == 2
    assert s["banner_promoted_gambling"] == 2
    assert s["rotation_groups"] == {"groups": 1, "domains": 2}
    assert s["redirected"] == 1


def test_rotation_requires_digits_removed():
    assert rotation_groups(["abc.com", "abc.net"]) == (0, 0)
    assert rotation_groups(["abc1.com", "abc.net"]) == (1, 2)


def test_open_share_variants():
    from detector.evidence import open_share_variants
    rows = [
        _r("a.com", "blocked_kr", "2026-09-30T10:00:00+09:00"),
        _r("a.com", "ok", "2026-10-07T10:00:00+09:00"),        # 최신=open
        _r("b.com", "ok", "2026-09-30T10:00:00+09:00"),
        _r("b.com", "blocked_kr", "2026-10-07T10:00:00+09:00"),  # 최신=blocked, 열림 이력 있음
        _r("c.com", "blocked_kr", "2026-09-30T10:00:00+09:00"),
        _r("c.com", "challenge", "2026-10-07T10:00:00+09:00"),  # 막힘 이력만, 최신=challenge
        _r("d.com", "ok", "2026-10-01T10:00:00+09:00"),
        _r("e.com", "ok", "2026-10-01T10:00:00+09:00", label="normal"),
    ]
    v = open_share_variants(rows)
    # 최신 상태: a open, b blocked, c challenge(제외), d open -> 2/3
    assert v["latest_status"] == {"open": 2, "blocked_kr": 1, "share": 2 / 3}
    # 열린 적 있으면 open(a,b,d=3), 열린 적 없고 막힘 이력만(c)=blocked -> 3/4
    assert v["blocked_if_never_open"] == {"open": 3, "blocked_kr": 1, "share": 0.75}


def test_seeds_ref_sha_recorded(tmp_path):
    import json, subprocess
    from detector.evidence import summarize_at_ref
    repo = tmp_path / "r"
    (repo / "seeds").mkdir(parents=True)
    h = "url,source,added_at,note\n"
    for n in ("gambling.csv", "embedded_banner.csv", "candidates.csv"):
        (repo / "seeds" / n).write_text(h, encoding="utf-8")
    g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True, text=True).stdout.strip()
    g("init", "-q")
    g("add", ".")
    g("commit", "-qm", "x")
    idx = tmp_path / "i.jsonl"
    idx.write_text(json.dumps(_r("a.com", "ok", "2026-10-01T00:00:00+09:00")), encoding="utf-8")
    s = summarize_at_ref(idx, repo, "HEAD")
    assert s["seeds_ref_sha"] == g("rev-parse", "HEAD")
    assert s["open_share_sensitivity"]["latest_status"]["open"] == 1


def test_report_md_shows_sensitivity_and_rotation_caveat(tmp_path):
    from detector.evidence import write_reports
    var = {"latest_status": {"open": 70, "blocked_kr": 10, "share": 0.875},
           "blocked_if_never_open": {"open": 78, "blocked_kr": 18, "share": 78 / 96}}
    s = {"gambling_domains_total": 121, "status_counts": {"open": 78, "blocked_kr": 8}, "open_share": 0.907,
         "open_share_sensitivity": var, "embedded_seeds": 1, "banner_links": 1, "banner_link_domains_unique": 1,
         "blocked_and_open": 1, "banner_promoted_gambling": 1, "rotation_groups": {"groups": 11, "domains": 22},
         "redirected": 1, "captured_from": "a", "captured_to": "b", "seeds_ref_sha": "abc123"}
    write_reports(s, tmp_path)
    md = (tmp_path / "problem_evidence.md").read_text(encoding="utf-8")
    assert "규칙에 따라 81~91%" in md and "70/80" in md and "78/96" in md
    assert "실제는 7~11묶음" in md
