from crawler.banners import BANNER_JS, Candidate, filter_candidates, from_js, href_domain, iou


def c(w, h, x=0, y=0, href=None, visible=True, tag="img"):
    return Candidate(tag=tag, x=x, y=y, w=w, h=h, visible=visible, src="s.png", href=href)


def test_from_js_maps_dicts():
    items = [{"tag": "img", "x": 1, "y": 2, "w": 300, "h": 100, "visible": True, "src": "a.png", "href": None}]
    assert from_js(items) == [Candidate("img", 1, 2, 300, 100, True, "a.png", None)]


def test_size_and_aspect_rules():
    kept = filter_candidates([
        c(300, 100),            # ok
        c(140, 100),            # 너비 < 150
        c(300, 30),             # 높이 < 40
        c(150, 79),             # 면적 < 12000
        c(1000, 50),            # 비율 20 > 8
        c(60, 400),             # 비율 0.15 < 0.2 (너비도 미달)
        c(300, 100, visible=False),
    ], page_domain="site.com", label="gambling")
    assert kept == [c(300, 100)]


def test_iou_dedup_keeps_larger_and_sorts_by_area():
    a = c(400, 100, x=0, y=0)
    a_dup = c(380, 100, x=10, y=0)      # a와 크게 겹침 → 제거
    b = c(300, 200, x=0, y=500)         # 면적 60000 → 첫 번째
    kept = filter_candidates([a, a_dup, b], "site.com", "gambling")
    assert kept == [b, a]
    assert iou(a, a_dup) >= 0.8


def test_max_n():
    cands = [c(300, 100, y=i * 200) for i in range(20)]
    assert len(filter_candidates(cands, "site.com", "gambling", max_n=12)) == 12


def test_embedded_banner_keeps_only_external_hrefs():
    internal = c(300, 100, y=0, href="https://www.site.com/event")
    external = c(300, 100, y=300, href="https://toto-x.com/join")
    none = c(300, 100, y=600)
    assert filter_candidates([internal, external, none], "site.com", "embedded_banner") == [external]
    assert href_domain(external) == "toto-x.com" and href_domain(none) is None


def test_banner_js_is_a_function_expression():
    assert BANNER_JS.lstrip().startswith("() =>") and "getBoundingClientRect" in BANNER_JS
