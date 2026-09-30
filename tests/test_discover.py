from crawler.discover import external_domains_urls, parse_ddg_links

DDG_HTML = '''
<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftoto%2Dverify.example%2Flist&amp;rut=abc">토토 검증</a></div>
<div class="result"><a class="result__a" href="https://direct.example/page">직접 링크</a></div>
<div class="result"><a class="result__snippet" href="https://ignored.example/">snippet</a></div>
'''


def test_parse_ddg_links_resolves_uddg_and_keeps_order():
    assert parse_ddg_links(DDG_HTML) == ["https://toto-verify.example/list", "https://direct.example/page"]


def test_external_domains_urls_filters_same_domain_platform_and_dups():
    hrefs = ["https://verify.com/a", "https://www.site-a.com/x", "https://site-a.com/y", "https://naver.com/blog",
             "javascript:void(0)", "https://site-b.net/", "https://t.me/chan"]
    assert external_domains_urls(hrefs, "verify.com") == ["https://www.site-a.com/x", "https://site-b.net/"]
