# 정상 쪽 탐색 경로 추가 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 야간 루프가 정상 쪽 키워드로도 후보를 찾아 같은 판정 절차로 `hard_negative` 사이트를 늘리게 한다.

**Architecture:** 후보의 출처 접두어(`search:` / `search-normal:`)로 두 경로를 구분한다. 검색·후보 선택·자동 키워드 확장·판정 추천 네 곳이 이 접두어를 본다. 후보 파일·판정표·승격 절차는 그대로 쓴다.

**Tech Stack:** Python 3.12, Playwright(async), pytest. 작업 폴더 `/Users/seongmin/gambling-content-detection-normal`(브랜치 `normal-track-discovery`).

**Spec:** `docs/superpowers/specs/2026-11-11-normal-track-discovery-design.md`

## Global Constraints

- 시험 실행: `cd /Users/seongmin/gambling-content-detection-normal && PYTHONPATH=src /Users/seongmin/gambling-content-detection/.venv/bin/python -m pytest -q -o tdd_guard_project_root=/Users/seongmin` (전체 약 95초, 기존 115개 통과 상태). 작업 중에는 해당 파일만 `tests/test_x.py -q` 로 돌린다.
- 시험을 먼저 쓰고(실패 확인) 구현한다.
- **커밋·푸시 금지.** 변경은 작업 트리에 둔다(사용자 승인 뒤 커밋).
- 네트워크에 나가는 실제 검색·수집은 하지 않는다. 시험은 기존 방식(가짜 페이지·fixture)으로 한다.
- 도박 쪽 기본 동작은 바뀌지 않는다: 새 인자는 모두 기본값이 지금 동작이다.
- 출처 접두어는 정확히 `search:`(도박), `search-normal:`(정상). 신호 이름은 정확히 `normal_track`. 추천 값은 `hard_negative`.
- 차단·접속 확인 우회, 로그인, 결제 코드는 넣지 않는다.
- 주석·출력 문구는 기존 코드처럼 한국어로 쓴다.

## Review Focus

1. 정상 쪽 검색 결과 0이 연속돼도 도박 쪽 조기 중단(bot_check) 판단과 `explore_state.json` 의 `bot_check_date` 에 영향을 주지 않는다 — Task 3 시험.
2. `candidates.csv` 에 정상 후보가 하나도 없을 때 후보 선택 결과가 지금과 완전히 같다 — Task 2 시험.
3. 같은 등록 도메인이 도박·정상 양쪽 출처로 들어와 있을 때 한 번만 뽑힌다(먼저 뽑힌 쪽) — Task 2 시험.
4. 정상 쪽 후보가 도박 신호를 가졌을 때 추천이 `gambling` 이다(정상 추천이 도박 규칙을 덮지 않는다) — Task 2 시험.
5. `keywords_normal.txt` 가 없거나 비어 있을 때 야간 루프가 오류 없이 지금처럼 돈다 — Task 3 시험.

---

### Task 1: 검색에 정상 경로 추가

**Files:**
- Modify: `src/crawler/discover.py`, `src/crawler/__main__.py`
- Create: `seeds/keywords_normal.txt`
- Test: `tests/test_discover.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `discover.NORMAL_SOURCE_PREFIX = "search-normal:"`
  - `discover.is_normal_source(source: str) -> bool` — `source.startswith(NORMAL_SOURCE_PREFIX)`
  - `discover.search_source(keyword: str, track: str = "gambling") -> str` — `"search:<kw>"` 또는 `"search-normal:<kw>"`. track 이 `gambling`·`normal` 이 아니면 `ValueError`
  - `discover_search_keywords(..., track: str = "gambling")`, `discover_search(..., track: str = "gambling")` — 후보 출처에 `search_source(kw, track)` 사용
  - CLI: `crawler discover search --track {gambling,normal}` (기본 `gambling`)

- [ ] **Step 1: 실패하는 시험 쓰기** — `tests/test_discover.py`
  - `test_search_source_prefix`: `search_source("토토사이트") == "search:토토사이트"`, `search_source("게임 캐시 충전", "normal") == "search-normal:게임 캐시 충전"`, `search_source("x", "etc")` 는 `ValueError`
  - `test_is_normal_source`: `search-normal:a` 는 True, `search:a`·`banner:x`·`community:y`·`""` 는 False
  - 기존 검색 시험이 쓰는 가짜 페이지 방식으로 `discover_search_keywords(..., track="normal")` 이 `candidates.csv` 에 `search-normal:<kw>` 로 적는지 확인(기존 시험에 그런 장치가 없으면 `search_source` 호출 지점을 단위로 확인할 수 있게 구조를 잡는다)
  - `tests/test_cli.py`: `discover search --track normal` 파싱, 기본값 `gambling`
- [ ] **Step 2: 시험이 실패하는지 확인**
- [ ] **Step 3: 구현** — 위 Interfaces 대로. `SearchTally` 는 건드리지 않는다
- [ ] **Step 4: `seeds/keywords_normal.txt` 만들기** — 첫 줄 주석 `# 정상 쪽 검색 키워드(Yahoo). 한 줄에 하나. 밤마다 nightly_search_normal 개씩 돌아가며 쓴다.` 다음에 종류 주석과 키워드 15개:
  - `# 게임 결제`: 게임 캐시 충전 / 게임 아이템 상점 / 모바일 게임 쿠폰
  - `# 상품권·간편결제`: 문화상품권 충전 / 포인트 충전소 / 기프트카드 구매
  - `# 스포츠`: 프로야구 경기 결과 / 축구 실시간 스코어 / e스포츠 중계
  - `# 금융`: 코인 거래소 / 주식 시세 / 환율 계산
  - `# 경품·이벤트`: 룰렛 이벤트 / 출석체크 이벤트 / 경품 응모
  - `read_keywords` 가 주석 줄을 건너뛰고 15개를 읽는지 시험 하나 추가
- [ ] **Step 5: 해당 시험 통과 확인**

### Task 2: 후보 선택·자동 키워드·판정 추천

**Files:**
- Modify: `src/crawler/config.py`, `src/crawler/explore.py`, `src/crawler/review.py`
- Test: `tests/test_explore.py`, `tests/test_review.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `discover.is_normal_source`, `discover.NORMAL_SOURCE_PREFIX` (순환 import 가 생기면 두 이름을 `seeds.py` 로 옮기고 `discover` 에서 다시 내보낸다)
- Produces:
  - `Settings.nightly_search_normal: int = 5`, `Settings.nightly_max_normal_candidates: int = 15`
  - `select_candidates(candidates_csv, max_n, blocklist=frozenset(), max_normal: int = 0) -> list[Seed]` — 반환 순서는 도박 쪽 먼저, 정상 쪽 다음. 정상은 `min(max_normal, max_n)` 곳까지, 도박은 `max_n − 뽑힌 정상 수` 곳까지. 각 쪽 안에서는 기존 규칙(`unverified` 만, `added_at` 최신순, 같은 등록 도메인은 첫 행만, blocklist 제외). 두 쪽에 같은 등록 도메인이 있으면 정상 쪽을 먼저 고른 뒤 도박 쪽에서는 뺀다
  - `ExploreResult.precaptured_normal: int = 0` — 판정표 행 중 정상 쪽 후보 수
  - `run_explore`: `select_candidates(..., max_normal=settings.nightly_max_normal_candidates)` 로 부르고, `expand_keywords` 에 넘기는 제목에서 정상 쪽 후보(선택된 Seed 의 source 가 정상인 등록 도메인)의 행을 뺀다
  - `review.signals`: 행 중 `seed_source` 가 `search-normal:` 로 시작하는 것이 있으면 `"normal_track"` 추가
  - `review.suggest`: 기존 규칙을 순서대로 본 뒤 결과가 빈칸이고 `"normal_track"` 이 있으면 `"hard_negative"`

- [ ] **Step 1: 실패하는 시험 쓰기**
  - `test_select_candidates_quota`: 정상 20·도박 50, `max_n=40, max_normal=15` → 도박 25 + 정상 15(도박이 앞)
  - `test_select_candidates_normal_short`: 정상 3·도박 50 → 도박 37 + 정상 3
  - `test_select_candidates_gambling_short`: 정상 20·도박 10 → 도박 10 + 정상 15
  - `test_select_candidates_no_normal_same_as_before`: 정상 후보가 없으면 `max_normal=15` 여도 결과가 `max_normal=0` 과 같다
  - `test_select_candidates_default_ignores_track`: `max_normal` 을 안 주면 정상 출처 후보도 지금처럼 최신순으로 섞여 뽑힌다(기존 동작 유지)
  - `test_select_candidates_same_domain_both_tracks`: 같은 등록 도메인이 두 출처에 있으면 한 번만
  - `test_signals_normal_track`, `test_suggest_normal_track_hard_negative`, `test_suggest_normal_track_with_gambling_signals_stays_gambling`, `test_suggest_normal_track_blocked`
  - `test_run_explore_excludes_normal_titles_from_keywords`: 정상 쪽 후보 제목의 단어가 `keywords_auto.txt` 에 들어가지 않는다(기존 `run_explore` 시험의 가짜 캡처 방식 사용). `precaptured_normal` 값 확인
  - `tests/test_config.py`: 새 설정 두 개의 기본값
- [ ] **Step 2: 시험이 실패하는지 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 해당 시험과 `tests/test_explore.py`·`tests/test_review.py`·`tests/test_promote.py` 전체 통과 확인**

### Task 3: 야간 루프 연결·보고서·문서

**Files:**
- Modify: `src/crawler/nightly.py`, `seeds/README.md`, `README.md`(크롤러 사용법에 한 단락), `scripts/README.md`(있으면 한 줄)
- Test: `tests/test_nightly.py`

**Interfaces:**
- Consumes: Task 1·2 의 모든 것, `keywords.pick_auto_keywords`(회전 고르기 — 정상 키워드에도 그대로 쓴다), `keywords.record_run(..., origin="normal")`
- Produces:
  - `Runner.normal_keywords() -> list[str]` — `seeds/keywords_normal.txt` 에서 `settings.nightly_search_normal` 개를 회전으로 고른다. 파일이 없거나 비면 `[]`
  - `Runner.stage_search`: 도박 키워드(수동 + 자동)를 지금처럼 먼저 돌린다. 그 뒤 도박 쪽이 `bot_check` 도 `timed_out` 도 아니고 정상 키워드가 있으면, **별도 tally** 로 `discover_search_keywords(..., track="normal", stop_after_zero=2, deadline=같은 마감)` 를 돌린다. 정상 쪽 실행 기록은 `record_run(..., origin="normal")`. 정상 쪽의 `bot_check` 는 `state["bot_check_date"]` 를 바꾸지 않는다. 반환 dict 에 `normal_keywords: list[str]`, `normal_candidates_added: int`, `normal_bot_check: bool` 추가(기존 키는 그대로)
  - `Runner.stage_explore` 반환 dict 에 `precaptured_normal` 추가
  - `build_report`·`dry_run_plan`: 정상 키워드 수(와 목록), 정상 쪽 추가 후보 수, 미리 찍은 정상 후보 수를 한 줄씩

- [ ] **Step 1: 실패하는 시험 쓰기** — `tests/test_nightly.py` (기존 Runner 시험의 가짜 단계·monkeypatch 방식 사용)
  - `test_normal_keywords_rotation`: 15개 중 `last_run` 이 없는 것·오래된 것부터 5개
  - `test_normal_keywords_missing_file`: 파일이 없으면 `[]`, `stage_search` 가 정상 검색을 부르지 않고 기존 결과와 같다
  - `test_stage_search_runs_normal_after_gambling`: `discover_search_keywords` 를 가짜로 바꿔 호출 순서와 `track` 인자 확인, state 에 origin `normal` 기록
  - `test_stage_search_skips_normal_on_bot_check`: 도박 쪽 tally 가 `bot_check` 면 정상 검색을 부르지 않는다
  - `test_normal_bot_check_does_not_set_bot_check_date`
  - `test_dry_run_plan_shows_normal`, 보고서에 정상 쪽 줄이 있는지
- [ ] **Step 2: 시험이 실패하는지 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 문서** — `seeds/README.md` 에 `keywords_normal.txt` 와 출처 접두어·후보 자리 설명, `README.md` 크롤러 사용법에 정상 쪽 경로 한 단락과 수동 실행 명령(`crawler discover search --keywords seeds/keywords_normal.txt --track normal`)
- [ ] **Step 5: 전체 시험 통과 확인** — 115 + 새 시험, 실패 0
- [ ] **Step 6: `PYTHONPATH=src …/python -m crawler nightly --dry-run` 을 돌려 정상 쪽 줄이 보이는지 확인**(네트워크에 나가지 않는 명령이다. `.env` 가 없어 실패하면 그 사실만 보고한다)
