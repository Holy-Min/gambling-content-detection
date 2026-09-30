from crawler.domains import registrable_domain, domain_hash, normalize_url, host_of


def test_registrable_domain_strips_subdomains():
    assert registrable_domain("https://www.seoul005.gtli.co.kr/a") == "gtli.co.kr"
    assert registrable_domain("http://sub.example.com") == "example.com"


def test_registrable_domain_for_ip_returns_ip():
    assert registrable_domain("http://127.0.0.1:8000/x") == "127.0.0.1"
    assert registrable_domain("https://toto-partner.example/join") == "toto-partner.example"


def test_domain_hash_is_12_hex_and_salted():
    h1 = domain_hash("example.com", "salt-a")
    h2 = domain_hash("example.com", "salt-b")
    assert len(h1) == 12 and all(c in "0123456789abcdef" for c in h1)
    assert h1 != h2
    assert h1 == domain_hash("example.com", "salt-a")


def test_normalize_url_drops_fragment_and_tracking_params():
    u = "HTTP://Example.COM/path?utm_source=x&b=2&fbclid=1&a=1#frag"
    assert normalize_url(u) == "http://example.com/path?b=2&a=1"


def test_normalize_url_adds_scheme_and_keeps_bare_path():
    assert normalize_url("example.com") == "http://example.com/"
    assert normalize_url("https://example.com/x?") == "https://example.com/x"


def test_host_of():
    assert host_of("https://WWW.Warning.or.kr/i.html") == "www.warning.or.kr"
