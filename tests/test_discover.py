from crawler.discover import external_domains_urls, parse_search_links, resolve_search_href


def test_resolve_search_href_unwraps_yahoo_redirect_and_drops_engine_links():
    wrapped = "https://r.search.yahoo.com/_ylt=Awr;_ylu=Y29s/RV=2/RE=1/RO=10/RU=https%3a%2f%2fmtpolice.kr%2fhome%2f/RK=2/RS=abc-"
    assert resolve_search_href(wrapped) == "https://mtpolice.kr/home/"
    assert resolve_search_href("https://mtcheck.net/main") == "https://mtcheck.net/main"
    assert resolve_search_href("https://search.yahoo.com/preferences") is None
    assert resolve_search_href("javascript:void(0)") is None


def test_parse_search_links_dedups_in_order():
    hrefs = ["https://mtpolice.kr/home/", "https://mtpolice.kr/home/", "https://jusotour.com/scam_verify", "https://s.yimg.com/x"]
    assert parse_search_links(hrefs) == ["https://mtpolice.kr/home/", "https://jusotour.com/scam_verify"]


def test_external_domains_urls_filters_same_domain_platform_and_dups():
    hrefs = ["https://verify.com/a", "https://www.site-a.com/x", "https://site-a.com/y", "https://naver.com/blog",
             "javascript:void(0)", "https://site-b.net/", "https://t.me/chan"]
    assert external_domains_urls(hrefs, "verify.com") == ["https://www.site-a.com/x", "https://site-b.net/"]
