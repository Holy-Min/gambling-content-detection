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
7. `python -m crawler stats`
