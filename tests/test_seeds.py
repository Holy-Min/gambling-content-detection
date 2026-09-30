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
