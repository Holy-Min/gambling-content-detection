# 야간 수집 루프와 시드 탐색(nightly · explore · promote) 설계

- 작성일: 2026-10-19
- 대상 저장소: gambling-content-detection
- 선행 스펙: `2026-09-23-gambling-crawler-design.md` (수집기 본체). 이 문서는 그 위에 얹는 자동화 계층만 다룬다.
- 상태: 승인됨 (구현 계획 작성 전)

## 1. 목표

자는 동안 매일 한 번, 사람 손 없이 **시드 탐색 → 후보 선캡처 → 기존 시드 재캡처 → 보고서**까지 돌리고, 아침에 사람은 스크린샷을 보며 후보의 판정만 적는다. 판정 반영은 명령 하나로 끝낸다.

- 매일 돈다. discover 와 capture 모두 하루 1회.
- 시드 풀이 스스로 자란다. 검색 키워드·검증 커뮤니티 목록·배너 링크에서 새 후보를 계속 만든다.
- 후보는 확정 전에도 화면을 찍어 둔다. URL 만 보고 판단하던 검토를 스크린샷 검토로 바꾼다.
- 라벨 편입은 사람이 한다. 자동 승격은 없다.

### 범위 밖

자동 승격, 로그인·가입·CAPTCHA 해결, VPN·프록시 우회, OCR·모델 학습, Claude 호출(추천값 생성 등), 회사 앱 야간 루프(`~/all-catcher-notes/loops`)와의 통합, 아침 요약 파일 병합.

## 2. 원칙

선행 스펙의 원칙은 그대로 유지하고 다음을 더한다.

- **사람이 한 번 검토한다 — 격리로 지킨다.** `capture` 는 확정 시드 파일만 읽는다. 후보 선캡처 결과는 본 데이터셋과 다른 루트(`_review/`)에 쓰고, 본 데이터셋 색인·통계에 섞이지 않는다.
- **모르는 사이트는 정상 사이트로 대한다.** 후보(라벨 미정)는 robots.txt 를 따르고 요청 간격 5초, 도메인당 2페이지, 메뉴 클릭 없음.
- **발자국 상한을 둔다.** 밤당 검색 키워드 15개, 선캡처 새 후보 40 도메인, 커뮤니티 자동 등록 5개.
- **보고서는 항상 나온다.** 단계가 실패해도 다음 단계와 보고서는 실행된다.
- **저장소에서 바뀌는 파일은 `seeds/` 와 `out/` 뿐이다.** git 명령은 쓰지 않는다. 코드·문서는 건드리지 않는다.
- **외부 바이너리에 기대지 않는다.** 이 Mac 에는 `timeout` 이 없다. 시간 예산은 파이썬(asyncio) 안에서 건다.

## 3. 구성

기존 패키지 `src/crawler/` 에 모듈 3개를 더하고 기존 4개를 조금 고친다.

| 모듈 | 책임 |
|---|---|
| `explore.py` (신규) | 키워드 확장(`extract_terms`, `rotate_keywords`), 커뮤니티 판정(`looks_like_community`), 신호·추천(`signals`, `suggest`), 후보 선캡처(`precapture`), `review.csv` 쓰기. 순수 함수와 브라우저 함수를 분리 |
| `promote.py` (신규) | `review.csv` 읽기·검증, 판정 적용: 시드 추가, 폴더 이동, meta/index 라벨·경로 재기록, `candidates.csv` note 갱신 |
| `nightly.py` (신규) | 단계 실행기(격리·시간 예산·잠금), 전일 대비 집계, `report.md`·`summary.json` 생성, 썸네일 |
| `__main__.py` | 명령 추가: `nightly`, `explore`, `promote` |
| `config.py` | `recapture_days`, `skip_blocked_days`, `review_root`, 야간 상한값 추가. `DEFAULT_OUT` 을 `/Users/seongmin/datasets/gambling` 으로 변경 |
| `capture.py` | meta 에 `text_excerpt`·`ext_domains` 추가, `seen_recently(days=settings.recapture_days)`, 최근 차단 도메인 건너뛰기 |
| `store.py` | `blocked_recently()`, 폴더 이동과 색인 재기록 헬퍼(`relabel_domain`), 색인 행 삭제 헬퍼 |
| `scripts/nightly.sh` (신규) | launchd 진입점. 저장소로 cd, `caffeinate -i` 로 `python -m crawler nightly` 실행, 로그 append |
| `scripts/launchd/com.gambling-crawler.nightly.plist` (신규) | 매일 04:30 실행 |

## 4. 명령

### `nightly [--date YYYY-MM-DD] [--out-dir out] [--only 단계[,단계]] [--skip 단계[,단계]] [--budget-min 90] [--dry-run]`

단계는 `search → community → explore → capture → report` 순서로 고정. `--dry-run` 은 단계마다 무엇을 얼마나 할지(키워드 목록, 선캡처 대상 수, 재캡처 대상 수)만 출력한다. 종료 코드: 0 전부 정상, 1 일부 단계 실패·부분 완료, 2 실행 불가(`.env` 없음, 잠금 파일 살아 있음, 저장 루트 쓰기 불가).

### `explore [--max-candidates 40] [--per-domain 2] [--date YYYY-MM-DD]`

야간 중 `explore` 단계만 따로 돌린다. 선캡처 + `review.csv` + 키워드 확장 + 커뮤니티 자동 등록까지 포함한다.

### `promote <out/날짜/review.csv> [--dry-run]`

사람이 `verdict` 를 채운 파일을 읽어 판정을 반영한다. 두 번 돌려도 안전해야 한다(이미 처리된 행은 건너뜀).

### `stats [--review]` (기존) 추가 옵션

`--review` 면 본 데이터셋 대신 리뷰 루트(`_review/index.jsonl`)를 집계한다. `candidate` 는 데이터셋 라벨이 아니므로 기본 `stats` 에는 나오지 않는다.

### `capture` (기존) 추가 옵션

`--recapture-days N` (기본 7, 야간은 1). 기존 `--refresh` 는 유지한다.

## 5. 야간 단계 세부

### 5.1 search — 검색 discover

- 키워드 = `seeds/keywords.txt`(수동, 10개) + `seeds/keywords_auto.txt` 에서 5개. 자동 키워드는 `seeds/explore_state.json` 의 `last_run` 이 가장 오래된 것부터 고른다(회전).
- 키워드당 결과 20개(기존 `--per-keyword`). 새 컨텍스트·4초 간격 규칙은 기존 그대로.
- 봇 확인 감지: 연속 2개 키워드에서 결과 링크가 0개면 단계를 멈추고 `bot_check` 로 기록한다. 그날 밤은 더 시도하지 않는다.
- 끝나면 키워드별 수확(추가된 후보 수)을 `explore_state.json` 에 누적한다. 예산 12분.

### 5.2 community — 커뮤니티 discover

- `seeds/community_lists.csv` 전체(사람이 넣은 행 + 자동 등록 행)에 대해 기존 `discover community` 를 돌린다. 예산 8분.

### 5.3 explore — 후보 선캡처와 시드 확장

1. **대상 선정.** `candidates.csv` 에서 note 가 `unverified` 인 행(아직 사람 검토도 선캡처도 안 된 행)을 `added_at` 최신순으로 최대 40개.
2. **선캡처.** 라벨 `candidate`, 루트 `review_root`(기본 `<CRAWLER_OUT>/_review`)의 `Store` 로 `run_capture` 를 호출한다. 도메인당 2페이지(홈 + 우선 내부 링크 1개), robots 준수·5초 간격, 메뉴 클릭 없음. 결과는 `_review/candidate/<도메인해시>/` 와 `_review/index.jsonl`.
3. **신호 계산과 추천.** 도메인마다 `signals()` 로 신호 목록을, `suggest()` 로 추천값을 낸다(6절).
4. **커뮤니티 자동 등록.** `looks_like_community()` 가 참인 도메인은 `community_lists.csv` 에 `source=auto:<날짜>`, `note=자동 등록(미검토)` 으로 추가한다. 밤당 5개까지. 다음 밤 5.2 단계가 이 페이지의 외부 링크를 모은다.
5. **`review.csv` 작성.** 선캡처한 모든 도메인을 한 줄씩 쓴다(7절). `candidates.csv` 의 해당 행 note 를 `review: <날짜>` 로 바꾼다(그래야 다음 밤 다시 고르지 않는다).
6. **키워드 확장.** 본 데이터셋 색인의 `gambling` ok 행 제목 + 오늘 선캡처 제목에서 `extract_terms()` 로 용어를 뽑는다. 규칙: 공백·구두점으로 자른 토큰 1~2개 묶음 중 `사이트·놀이터·검증·카지노·토토·슬롯·바카라·파워볼·홀덤·릴게임` 으로 끝나는 것, 길이 3~12자, 기존 수동·자동 키워드와 다른 것. 등장 횟수 순으로 하루 최대 5개를 `keywords_auto.txt` 에 추가하되 풀은 30개 상한. `zero_streak`(돌렸는데 후보 0인 연속 횟수)가 3 이상인 자동 키워드는 퇴역시켜 파일에서 지우고 state 에 `retired` 로 남긴다.

예산 25분. 예산이 끝나면 선캡처를 중단하고 그때까지의 결과로 3~6 을 수행한다.

### 5.4 capture — 기존 시드 재캡처

라벨 순서 `gambling(--click-menus) → embedded_banner(--emit-candidates) → hard_negative → normal`. 설정은 `recapture_days=1`, `skip_blocked_days=7`, 나머지 기본값. 화면이 그대로인 페이지는 기존 phash 규칙으로 `duplicate` 처리되어 파일이 남지 않는다. 라벨 하나가 끝날 때마다 남은 예산을 확인하고, 모자라면 남은 라벨은 `skipped(budget)` 로 보고한다. 예산 40분.

### 5.5 report — 보고서

`out/<날짜>/report.md`, `summary.json`, `thumbs/`. 내용은 8절.

## 6. 신호와 추천 규칙

전부 결정적 규칙이다. 추천값은 사람의 검토를 돕는 힌트일 뿐 라벨이 아니다.

| 신호 | 판정 기준 |
|---|---|
| `ref_param` | 시드 URL 또는 final_url 의 쿼리 키에 `code, ref, aff, partner, invite, recommend, rec, 추천` 중 하나 |
| `tld_gambling` | 등록 도메인 접미사가 `.bet .casino .poker .vip .win` 중 하나 |
| `idn` | 도메인에 `xn--` |
| `numeric` | 도메인 라벨에 숫자 3자리 이상 |
| `deposit_page` | 선캡처 페이지 중 `page_kind` 가 `deposit · register · login` 인 것이 있음 |
| `menu_terms` | `text_excerpt` 에 `충전·입금·출금·환전·가입·배팅·베팅·카지노·슬롯·바카라·파워볼` 중 2종 이상 |
| `many_ext` | 홈의 `ext_domains` 가 8개 이상 |
| `verify_terms` | 제목 또는 `text_excerpt` 에 `먹튀·검증·보증업체·보증·커뮤니티` 중 하나 |
| `blocked_kr` / `challenge` / `error` | 홈 상태 |

`suggest()` 우선순위:
1. 홈 상태 `blocked_kr` → `blocked`
2. `many_ext` 그리고 `verify_terms` → `community`
3. (`deposit_page` 또는 `menu_terms`) 그리고 `many_ext` 아님 → `gambling`
4. `ref_param · tld_gambling · idn · numeric` 중 2개 이상 → `gambling`
5. 그 외 → 빈 값

`looks_like_community()` = 2번 조건과 같다. 커뮤니티 자동 등록은 이 함수만 쓴다.

## 7. `review.csv` 와 `promote`

### 파일 규격

`out/<날짜>/review.csv`, 컬럼 `domain,url,title,status,signals,suggested,verdict,note,review_dir`. `signals` 는 `|` 로 이은 문자열. `verdict` 와 `note` 만 사람이 채운다. `review_dir` 은 `_review/candidate/<해시>` 상대 경로.

`verdict` 허용값: `gambling · embedded_banner · hard_negative · normal · community · exclude · blocked`, 빈 값은 "아직 판단 안 함".

### 판정별 처리

| verdict | 시드 | 데이터 | `candidates.csv` note |
|---|---|---|---|
| 라벨 4종 | `seeds/<라벨>.csv` 에 추가, `source=review:<날짜>`, note 는 사람 note 또는 `nightly 승격` | `_review/candidate/<해시>` → `<루트>/<라벨>/<해시>` 이동. `meta.jsonl` 의 `label`·`full_path`·`banners[].path` 접두를 고쳐 쓰고 같은 행을 본 `index.jsonl` 에 추가. `_review/index.jsonl` 에서 해당 도메인 행 제거 | `→ <라벨>.csv (review <날짜>)` |
| `community` | `community_lists.csv` 에 추가, `source=review:<날짜>` | 리뷰 폴더·색인 행 삭제 | `→ community_lists.csv (review <날짜>)` |
| `exclude` | 없음 | 리뷰 폴더·색인 행 삭제 | `excluded: <사람 note 또는 '검토 제외'>` |
| `blocked` | 없음 | 리뷰 폴더·색인 행 삭제 | `blocked_kr <날짜>` |
| 빈 값 | 없음 | 그대로 둠 | 그대로 둠 |

- 허용되지 않은 `verdict` 가 하나라도 있으면 아무것도 바꾸지 않고 행 번호와 함께 거부한다.
- `review_dir` 이 이미 없으면 처리된 행으로 보고 건너뛴다(재실행 안전).
- `--dry-run` 은 행별 계획만 출력한다.
- 자동 등록된 커뮤니티 행(`source=auto:`)이 `exclude` 판정을 받으면 `community_lists.csv` 에서도 지운다. `community` 판정인데 같은 등록 도메인이 이미 있으면 줄을 더하지 않고 그 줄의 `source` 를 `review:<날짜>` 로 고친다(중복 줄 금지).

## 8. 보고서

`report.md` 구성(한국어 Markdown):

1. **요약 3줄** — 돌린 단계와 종료 코드, 새 ok 화면 수, 아침에 볼 것(검토 대기 N건, 실패 단계).
2. **단계 결과 표** — 단계 · 상태(ok/partial/failed/skipped) · 소요 · 핵심 수치(추가 후보, 선캡처 도메인, 라벨별 ok/duplicate/blocked_kr).
3. **라벨별 전일 대비** — 본 데이터셋 색인에서 오늘 `captured_at` 행을 상태별로 세고 누적 ok 와 함께 표로.
4. **검토 대기** — `review.csv` 링크 + 도메인별 썸네일(홈 전체 화면을 폭 160px 로 축소한 PNG, `thumbs/`)·제목·신호·추천값 표. 최대 40행.
5. **시드 변화** — 새 자동 키워드, 퇴역 키워드, 자동 등록 커뮤니티, 후보 추가 수(source 별).
6. **실패·경고** — 예외 요약, 봇 확인, 예산 초과, 30일 넘게 판정 안 된 리뷰 폴더 수.

`summary.json` 은 같은 수치를 기계용으로 담는다. `out/` 은 `.gitignore` 에 넣는다. `out/` 안의 날짜 폴더는 30일이 지나면 `nightly` 가 지운다(`review.csv` 는 남긴다).

## 9. 저장 규격 변경

- 저장 루트 기본값 `/Users/seongmin/datasets/gambling` (10/19 이동 완료, `.env` 의 `CRAWLER_OUT` 도 동일). 리뷰 루트 기본값 `<루트>/_review`, 환경변수 `CRAWLER_REVIEW` 로 바꿀 수 있다.
- 리뷰 루트도 `Store` 규격을 그대로 쓴다: `_review/index.jsonl`, `_review/candidate/<해시>/meta.jsonl` 과 PNG.
- meta 추가 필드: `text_excerpt`(본문 앞 300자, 공백 정리), `ext_domains`(홈의 외부 링크 등록 도메인, 최대 20개, 플랫폼 제외). 기존 행에는 없으므로 읽는 쪽은 빈 값으로 취급한다.
- `seeds/keywords_auto.txt`: 첫 줄 `# 자동 키워드 — nightly 가 관리. 손으로 고치려면 keywords.txt 를 쓸 것`. 한 줄에 하나.
- `seeds/explore_state.json`: `{"keywords": {"<kw>": {"origin": "manual|auto", "runs": n, "added_total": n, "zero_streak": n, "last_run": "YYYY-MM-DD", "retired": bool}}, "bot_check_date": "YYYY-MM-DD|null"}`.
- `out/<날짜>/`: `report.md`, `summary.json`, `review.csv`, `run.log`, `thumbs/`. `out/.lock` 에 PID.

## 10. 재캡처 정책

- `recapture_days` 가 `Store.seen_recently()` 의 날짜 창이 된다. 수동 실행 기본은 7일(지금과 같음), 야간은 1일.
- `Store.blocked_recently(label, domain, days)`: 그 도메인 홈(idx 0) 의 최근 상태가 `blocked_kr` 이고 `days` 안이면 참. `capture_domain` 은 참이면 도메인을 통째로 건너뛰고 요약의 `skipped_blocked` 를 센다. 같은 ISP 에서 매일 다시 두드려도 결과가 같기 때문이다. `challenge` 는 풀릴 수 있으므로 건너뛰지 않는다.
- 변하지 않은 화면은 `duplicate` 로 기록만 남고 파일은 지워진다(기존 규칙). 색인 행은 쌓이므로 보고서가 그 수를 보여 준다.
- 용량 추정: 현재 542MB/376행. 매일 선캡처 최대 80페이지 + 변경된 화면 수십 장이면 월 1~2GB. `datasets/` 는 TCC 보호 밖이라 launchd 가 쓸 수 있다.

## 11. 오류 처리

- 단계는 각각 코루틴이고 `asyncio.wait_for(stage(), budget)` 으로 감싼다. 시간 초과·예외는 단계 결과 `{status, error, elapsed, counts}` 로 삼키고 다음 단계로 간다. `store.record()` 가 페이지마다 바로 기록하므로 중단돼도 그때까지의 수집은 남는다.
- 잠금: 시작 시 `out/.lock` 이 있고 그 PID 가 살아 있으면 종료 코드 2. 죽은 PID 면 지우고 진행.
- 실행 불가 조건(종료 2): `.env` 또는 `CRAWLER_SALT` 없음, 저장 루트에 쓸 수 없음, Playwright 브라우저 실행 실패.
- 검색 봇 확인은 5.1 규칙으로 그날 밤만 멈춘다. 다음 밤은 다시 한 번 시도한다.
- `report` 단계는 다른 단계의 성패와 무관하게 실행되며, 보고서 생성 자체가 실패하면 `run.log` 에 스택을 남기고 종료 코드 1.

## 12. 테스트

- `tests/test_explore.py`: `extract_terms`(SEO 제목 예시 → 용어, 길이·접미사·중복 규칙), `rotate_keywords`(LRU 선택, 풀 상한, 퇴역), `signals`·`suggest`(표 기반 사례, 우선순위), `looks_like_community`, `review.csv` 쓰기·읽기 왕복.
- `tests/test_promote.py`: 임시 루트에 가짜 리뷰 폴더·색인·시드를 만들고 판정 7종을 각각 적용 → 폴더 이동, meta/index 재기록, 시드 추가, note 갱신, 재실행 시 무변화, `--dry-run` 무변화, 잘못된 verdict 거부.
- `tests/test_nightly.py`: 가짜 단계(정상·예외·시간 초과)로 실행기 → 상태·종료 코드·보고서 생성·잠금 파일 동작.
- `tests/test_capture_integration.py` 확장: 픽스처에 `community.html`(외부 링크 10개 + "먹튀검증" 문구)을 더해 `precapture` 가 그 페이지에 `community`, 기존 픽스처 홈에 `gambling` 을 추천하는지, `recapture_days=0` 과 `blocked_recently` 건너뛰기, `text_excerpt`·`ext_domains` 기록을 확인.
- `tests/test_cli.py`: 새 명령·옵션 파싱.

## 13. 운영

- `scripts/nightly.sh`: 저장소로 cd → `caffeinate -i .venv/bin/python -m crawler nightly >> out/launchd.log 2>&1`. 종료 코드를 그대로 돌려준다.
- `scripts/launchd/com.gambling-crawler.nightly.plist`: `StartCalendarInterval` 04:30, `WorkingDirectory` 저장소, 최소 PATH. 설치 `cp` + `launchctl bootstrap gui/$(id -u) …`, 해제 `launchctl bootout`. README 에 적는다.
- 전제: 전원 연결, 잠자기 방지 또는 `pmset repeat wake`, 가정용 ISP(차단은 `blocked_kr` 로 기록되는 것이 정상). 회사 앱 루프(02:00, 최대 150분)와 겹치지 않도록 04:30.
- 아침 루틴: `out/<날짜>/report.md` 열기 → `review.csv` 의 `verdict` 채우기 → `crawler promote out/<날짜>/review.csv`.
- 저장소 이동(10/19 완료): `~/gambling-content-detection`, dataset `~/datasets/gambling`. venv 의 절대 경로는 치환했고 테스트 52개 통과 확인. PyCharm 은 새 경로로 다시 연다.

## 14. 윤리·법적 고려

선행 스펙 11절을 그대로 따른다. 추가로: 선캡처는 라벨을 모르는 사이트를 여는 일이므로 정상 사이트 기준(robots·5초)을 적용하고 클릭을 하지 않는다. 리뷰 폴더의 화면은 판정 전까지 로컬에만 있고 저장소에 들어가지 않는다. 자동 등록된 커뮤니티도 사람이 `exclude` 로 되돌릴 수 있다. 수집 데이터는 계속 저장소 밖에 둔다.

## 15. 후속 작업(이 스펙 밖)

- 추천값을 Claude(`claude -p`)로 보강하고 근거 문장을 붙이기.
- 아침 요약을 회사 루프 `morning/` 과 같은 형식으로 쓸지 결정.
- `blocked_kr` 도메인을 다른 망(모바일 핫스팟)에서 재시도하는 `--network` 표시.
- `embedded_banner` 시드 자동 발견(무료 중계·웹툰 검색).
- `prune`·`reclassify`·`import` 명령.
