# 시드 파일

| 파일 | 용도 | 누가 채우나 |
|---|---|---|
| gambling.csv | 도박 사이트 (라벨 gambling) | candidates.csv를 검토해 사람이 옮김 |
| embedded_banner.csv | 무료 중계·웹툰 등 정상 서비스 속 도박 배너 | 사람이 직접 |
| hard_negative.csv | 합법 스포츠토토·경기정보·캐주얼 게임·주식 등 | 사람이 직접 |
| normal.csv | 뉴스·쇼핑·커뮤니티 일반 화면 | 사람이 직접 |
| community_lists.csv | 검증 커뮤니티 페이지 (discover community 입력) | 사람이 직접 |
| candidates.csv | 자동 발견 결과. **capture는 이 파일을 직접 읽지 않는다** | discover / capture --emit-candidates |
| keywords.txt | discover search 키워드 (Yahoo 검색) | 사람이 직접 |
| blocklist.txt | 어떤 경우에도 열지 않을 도메인 | 사람이 직접 |

컬럼: `url,source,added_at,note`. 같은 등록 도메인은 첫 줄만 쓰인다.

## 실행 순서

1. `.env`에 `CRAWLER_SALT`(긴 임의 문자열)와 필요하면 `CRAWLER_OUT`을 적는다.
2. `python -m crawler discover search` / `python -m crawler discover community` → candidates.csv
3. candidates.csv를 훑어 도박 사이트만 gambling.csv로 옮긴다(검증 커뮤니티 자체는 community_lists.csv로).
4. `python -m crawler capture --label embedded_banner --seeds seeds/embedded_banner.csv --emit-candidates`
5. `python -m crawler capture --label gambling --seeds seeds/gambling.csv`
6. `python -m crawler capture --label hard_negative --seeds seeds/hard_negative.csv` (robots.txt·5초 간격 자동 적용), normal도 같은 방식
   - 수동 `capture` 도 `--recapture-days`(기본 7)가 지난 도메인은 다시 열어 `duplicate` 행을 남길 수 있다. 예전처럼 새 시드만 돌리려면 `--recapture-days 99999`.
7. `python -m crawler stats`

## 야간 루프가 바꾸는 파일

- `candidates.csv`: discover 가 `unverified` 로 추가하고, 선캡처하면 note 를 `review: <날짜>` 로, `promote` 가 판정 결과(`→ gambling.csv (review <날짜>)`, `excluded: …`, `blocked_kr <날짜>`)로 바꾼다.
- `community_lists.csv`: 선캡처 페이지가 커뮤니티로 보이면 `source=auto:<날짜>`, `note=자동 등록(미검토)` 로 추가된다. `exclude` 판정이면 지워진다.
- `keywords_auto.txt`, `explore_state.json`: 자동 키워드와 수확 기록. 손으로 고칠 키워드는 `keywords.txt` 에만.
- 라벨 시드 4개: `promote` 가 `source=review:<날짜>` 로 추가한다.
