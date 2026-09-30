from crawler.blocked import is_blocked_kr


def test_blocked_by_host():
    assert is_blocked_kr("https://www.warning.or.kr/i.html", "")
    assert is_blocked_kr("http://warning.or.kr/", "아무 내용")


def test_blocked_by_notice_text():
    body = "불법·유해정보(사이트)에 대한 차단 안내 ... 이 사이트는 접속이 차단되었습니다."
    assert is_blocked_kr("https://some-toto.com/", body)


def test_blocked_by_kcsc_and_block_word():
    assert is_blocked_kr("https://x.com/", "방송통신심의위원회의 심의 결과에 따라 차단된 페이지입니다")


def test_not_blocked_normal_page():
    assert not is_blocked_kr("https://news.example.com/", "방송통신심의위원회가 회의를 열었다")  # '차단' 없음
    assert not is_blocked_kr("https://toto.example/", "첫 충전 100% 보너스")
