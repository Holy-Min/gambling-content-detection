from crawler.keywords import expand, extract_terms, load_state, pick_auto_keywords, record_run, save_state


def test_extract_terms_counts_suffix_terms_once_per_title():
    titles = ["토토사이트 추천 | 안전놀이터 먹튀검증 메이저사이트 순위",
              "안전놀이터 모음 - 안전놀이터 추천 2026",
              "Best Casino Online",
              "사이트 토토 1xbet 홀덤사이트"]
    got = extract_terms(titles, known={"토토사이트"})
    assert got[0] == ("안전놀이터", 2)                      # 제목당 한 번만 센다
    terms = dict(got)
    assert "토토사이트" not in terms and "사이트" not in terms and "토토" not in terms   # 알려진 것·접미사 자체·2글자 제외
    assert terms["먹튀검증"] == 1 and terms["메이저사이트"] == 1 and terms["홀덤사이트"] == 1
    assert "추천 안전놀이터" in terms                        # 앞 토큰이 한글이면 2토큰 용어도 후보
    assert "1xbet 홀덤사이트" not in terms                   # 앞 토큰에 숫자
    assert all(3 <= len(t) <= 12 for t in terms)
    assert extract_terms([], known=set()) == []


def test_state_roundtrip_and_rotation(tmp_path):
    p = tmp_path / "state.json"
    state = load_state(p)
    assert state == {"keywords": {}, "bot_check_date": None}
    record_run(state, "a", added=2, today="2026-10-18", origin="auto")
    record_run(state, "b", added=0, today="2026-10-19", origin="auto")
    record_run(state, "b", added=0, today="2026-10-20", origin="auto")
    assert state["keywords"]["b"] == {"origin": "auto", "runs": 2, "added_total": 0, "zero_streak": 2, "last_run": "2026-10-20", "retired": False}
    assert state["keywords"]["a"]["added_total"] == 2 and state["keywords"]["a"]["zero_streak"] == 0
    save_state(p, state)
    assert load_state(p) == state
    assert pick_auto_keywords(state, ["a", "b", "c", "d"], 2) == ["c", "d"]   # 한 번도 안 돌린 것 먼저
    assert pick_auto_keywords(state, ["a", "b"], 1) == ["a"]                 # 그다음 가장 오래된 것


def test_expand_retires_and_adds_within_caps():
    state = {"keywords": {
        "old": {"origin": "auto", "runs": 3, "added_total": 0, "zero_streak": 3, "last_run": "2026-10-19", "retired": False},
        "gone": {"origin": "auto", "runs": 1, "added_total": 0, "zero_streak": 0, "last_run": None, "retired": True}},
        "bot_check_date": None}
    auto = ["old", "keep"]
    terms = [("gone", 5), ("새사이트", 4), ("keep", 3), ("다른놀이터", 2), ("셋째카지노", 1)]
    new, added, retired = expand(state, auto, terms, add_per_day=2, pool=30, retire_streak=3)
    assert retired == ["old"] and state["keywords"]["old"]["retired"] is True
    assert added == ["새사이트", "다른놀이터"] and new == ["keep", "새사이트", "다른놀이터"]   # 퇴역·기존·이미 퇴역한 용어는 건너뜀
    assert state["keywords"]["새사이트"] == {"origin": "auto", "runs": 0, "added_total": 0, "zero_streak": 0, "last_run": None, "retired": False}
    new2, added2, retired2 = expand(state, new, [("넷째사이트", 1)], add_per_day=5, pool=3, retire_streak=3)
    assert added2 == [] and retired2 == [] and new2 == new   # 풀 상한
