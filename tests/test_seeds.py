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


from crawler.seeds import (  # noqa: E402
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
