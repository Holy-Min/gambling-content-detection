from crawler.stats import format_table, summarize


def test_summarize_counts_domains_pages_banners_per_label():
    rows = [
        {"label": "gambling", "domain": "a.com", "status": "ok", "banners": [{}, {}]},
        {"label": "gambling", "domain": "a.com", "status": "duplicate", "banners": []},
        {"label": "gambling", "domain": "b.com", "status": "blocked_kr", "banners": []},
        {"label": "normal", "domain": "n.com", "status": "ok", "banners": [{}]},
    ]
    s = summarize(rows)
    assert s["gambling"] == {"domains": 2, "ok": 1, "blocked_kr": 1, "challenge": 0, "error": 0, "duplicate": 1, "robots_disallow": 0, "banners": 2}
    assert s["normal"]["banners"] == 1 and s["normal"]["domains"] == 1
    table = format_table(s)
    assert "gambling" in table and "blocked_kr" in table
