from crawler.blocked import is_blocked_kr, is_challenge_page


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


def test_challenge_page_detection():
    assert is_challenge_page("잠시만 기다리십시오…", "stake.com 의 보안을 확인하는 중")
    assert is_challenge_page("Just a moment...", "")
    assert is_challenge_page("", "법적 사유로 이용 불가 이 서비스는 귀하의 지역에서 제공되지 않습니다")
    assert is_challenge_page("Security Check", "4 + 1 = ? Attempt 1/30")
    assert not is_challenge_page("메가파워월드", "파워볼 실시간 배팅 첫 충전 보너스")
