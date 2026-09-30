from crawler.capture import pick_internal_links


def test_pick_internal_links_prefers_keywords_and_same_domain():
    hrefs = ["https://site.com/about", "https://other.com/x", "https://site.com/event/1", "https://www.site.com/notice",
             "https://site.com/", "https://site.com/about#top", "mailto:a@b.c", "https://site.com/casino"]
    got = pick_internal_links(hrefs, "site.com", current_url="https://site.com/", n=3)
    assert got == ["https://site.com/event/1", "https://www.site.com/notice", "https://site.com/casino"]


def test_pick_internal_links_falls_back_to_first_unique():
    hrefs = ["https://site.com/a", "https://site.com/a?x=1#f", "https://site.com/b"]
    assert pick_internal_links(hrefs, "site.com", current_url="https://site.com/", n=5) == ["https://site.com/a", "https://site.com/a?x=1", "https://site.com/b"]
