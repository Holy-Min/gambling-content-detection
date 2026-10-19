from crawler.review import REVIEW_HEADER, VERDICTS, ReviewRow, build_row, looks_like_community, read_review_csv, signals, suggest, write_review_csv


def row(idx, **kw):
    base = {"id": f"h_20261020T043000_{idx}", "status": "ok", "url": f"https://site.com/{idx}", "final_url": None, "title": "",
            "text_excerpt": "", "ext_domains": [], "page_kind": "home" if idx == 0 else "other", "captured_at": "2026-10-20T04:30:00+09:00"}
    base.update(kw)
    return base


def test_signals_table():
    assert signals("x.bet", [row(0, url="https://x.bet/?code=abc")]) == ["ref_param", "tld_gambling"]
    assert signals("y.com", [row(0, final_url="https://y.com/?Ref=7")]) == ["ref_param"]
    assert "idn" in signals("xn--oy2b17xfhh.com", [row(0)])
    assert "numeric" in signals("gdct18110.com", [row(0)]) and "numeric" not in signals("six-16.com", [row(0)])
    s = signals("op.com", [row(0, text_excerpt="실시간 배팅 첫 충전 보너스", ext_domains=["a.com", "b.com"]), row(1, page_kind="deposit")])
    assert s == ["deposit_page", "menu_terms"]
    s = signals("verify.net", [row(0, title="먹튀검증 커뮤니티", ext_domains=[f"d{i}.com" for i in range(8)])])
    assert s == ["many_ext", "verify_terms"]
    assert signals("b.com", [row(0, status="blocked_kr")]) == ["blocked_kr"]
    assert signals("plain.com", [row(0, text_excerpt="충전")]) == []   # 메뉴 용어 1종은 부족
    assert signals("none.com", []) == []


def test_suggest_priority_and_community():
    assert suggest(["blocked_kr", "deposit_page"]) == "blocked"
    assert suggest(["many_ext", "verify_terms", "menu_terms"]) == "community"
    assert suggest(["deposit_page"]) == "gambling" and suggest(["menu_terms", "many_ext"]) == ""
    assert suggest(["ref_param", "numeric"]) == "gambling" and suggest(["numeric"]) == ""
    assert suggest([]) == ""
    assert looks_like_community(["many_ext", "verify_terms"]) and not looks_like_community(["many_ext"])


def test_build_row_and_csv_roundtrip(tmp_path):
    rows = [row(0, title='테스트, "도박" 사이트', text_excerpt="충전 입금"), row(1, page_kind="deposit")]
    r = build_row("site.com", "https://site.com/", rows, "/x/_review/candidate/h")
    assert r.title.startswith("테스트") and r.status == "ok" and r.signals == ["deposit_page", "menu_terms"] and r.suggested == "gambling"
    assert r.verdict == "" and r.review_dir == "/x/_review/candidate/h"
    p = tmp_path / "review.csv"
    write_review_csv(p, [r, ReviewRow(domain="b.com", url="https://b.com/", title="", status="blocked_kr", signals=["blocked_kr"], suggested="blocked")])
    back = read_review_csv(p)
    assert back[0] == r and back[1].signals == ["blocked_kr"] and back[1].verdict == "" and back[1].suggested == "blocked"
    assert p.read_text(encoding="utf-8").splitlines()[0] == ",".join(REVIEW_HEADER)
    assert VERDICTS == ("gambling", "embedded_banner", "hard_negative", "normal", "community", "exclude", "blocked", "")
