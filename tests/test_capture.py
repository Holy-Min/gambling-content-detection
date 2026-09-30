from crawler.capture import menu_targets, page_kind, pick_internal_links


def test_menu_targets_orders_deposit_first_dedupes_text_and_keeps_internal_href():
    items = [
        {"key": 0, "text": "회원가입", "tag": "a", "href": "https://site.com/#"},          # '#'뿐인 href → 클릭 대상
        {"key": 1, "text": "입금신청", "tag": "button", "href": ""},
        {"key": 2, "text": "충전하기", "tag": "a", "href": "https://site.com/charge"},     # 진짜 내부 URL → 이동 대상
        {"key": 3, "text": "입금신청", "tag": "span", "href": ""},                        # 같은 글자 중복
        {"key": 4, "text": "충전 이벤트 안내 공지사항 보기 바로가기", "tag": "a", "href": ""},  # 메뉴가 아닌 긴 글
        {"key": 5, "text": "충전", "tag": "a", "href": "https://other.com/charge"},        # 외부 링크는 제외
        {"key": 6, "text": "이벤트", "tag": "a", "href": ""},                             # 키워드 없음
        {"key": 7, "text": "JOIN", "tag": "a", "href": "javascript:void(0)"},            # javascript: → 클릭 대상
    ]
    got = menu_targets(items, "site.com")
    assert [(t.key, t.kind, t.href) for t in got] == [
        (1, "deposit", None), (2, "deposit", "https://site.com/charge"), (0, "register", None), (7, "register", None)]


def test_menu_targets_prefers_anchor_over_wrapper_with_same_text():
    items = [{"key": 0, "text": "충전", "tag": "li", "href": ""}, {"key": 1, "text": "충전", "tag": "a", "href": "https://site.com/m/12"}]
    got = menu_targets(items, "site.com")
    assert [(t.key, t.href) for t in got] == [(1, "https://site.com/m/12")]


def test_pick_internal_links_prefers_keywords_and_same_domain():
    hrefs = ["https://site.com/about", "https://other.com/x", "https://site.com/event/1", "https://www.site.com/notice",
             "https://site.com/", "https://site.com/about#top", "mailto:a@b.c", "https://site.com/casino"]
    got = pick_internal_links(hrefs, "site.com", current_url="https://site.com/", n=3)
    assert got == ["https://site.com/event/1", "https://www.site.com/notice", "https://site.com/casino"]


def test_pick_internal_links_puts_deposit_and_join_first():
    hrefs = ["https://site.com/event/1", "https://site.com/join", "https://site.com/charge", "https://site.com/about", "https://site.com/deposit?x=1"]
    got = pick_internal_links(hrefs, "site.com", current_url="https://site.com/", n=4)
    assert got == ["https://site.com/charge", "https://site.com/deposit?x=1", "https://site.com/join", "https://site.com/event/1"]


def test_page_kind():
    assert page_kind("https://s.com/charge", "충전", "", 1) == "deposit"
    assert page_kind("https://s.com/x", "안내", "충전 금액을 입력하고 입금 계좌를 확인하세요", 2) == "deposit"
    assert page_kind("https://s.com/join", "회원가입", "", 1) == "register"
    assert page_kind("https://s.com/", "홈", "환영합니다", 0) == "home"
    assert page_kind("https://s.com/member", "로그인", "아이디 비밀번호 로그인", 1) == "login"
    assert page_kind("https://s.com/notice", "공지", "이벤트 안내 " * 100, 1) == "other"


def test_pick_internal_links_falls_back_to_first_unique():
    hrefs = ["https://site.com/a", "https://site.com/a?x=1#f", "https://site.com/b"]
    assert pick_internal_links(hrefs, "site.com", current_url="https://site.com/", n=5) == ["https://site.com/a", "https://site.com/a?x=1", "https://site.com/b"]
