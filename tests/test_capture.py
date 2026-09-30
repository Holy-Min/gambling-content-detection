from crawler.capture import page_kind, pick_internal_links


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
