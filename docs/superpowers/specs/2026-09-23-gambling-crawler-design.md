# 도박 화면 데이터셋 수집기(crawler) 설계

- 작성일: 2026-09-23
- 대상 저장소: gambling-content-detection
- 상태: 승인됨 (구현 계획 작성 전)

## 1. 목표

논문·캡스톤 실험용 한국어 도박 화면 데이터셋을 모으는 커맨드라인 도구다. 실제 모바일 브라우저로 페이지를 렌더링해 **전체 화면 스크린샷 1장 + 배너 후보 크롭 N장 + 메타데이터**를 페이지마다 남긴다. 라벨 4종을 같은 도구로 수집하되 시드 목록만 다르게 준다.

| 라벨 | 뜻 | 시드 출처 |
|---|---|---|
| `gambling` | 불법 도박 사이트 자체 화면 | 검증 커뮤니티 링크, 검색 키워드, 배너 링크 대상 |
| `embedded_banner` | 무료 중계·웹툰 등 정상 서비스 화면 속 도박 배너 | 사용자가 준 중계·웹툰 사이트 목록 |
| `hard_negative` | 합법 스포츠토토·경기정보·캐주얼 게임·주식 등 겉이 비슷한 정상 화면 | 사용자가 준 목록 |
| `normal` | 뉴스·쇼핑·커뮤니티 등 일반 화면 | 사용자가 준 목록 |

목표 규모는 200개 이상 도메인, 도메인당 3~5페이지, 총 2,000~3,000장이다. 도메인 단위 train/test 분리를 위해 모든 결과에 도메인 해시를 남긴다.

### 범위 밖

OCR, 라벨링 UI, 스케줄러, 프록시·VPN 우회, CAPTCHA 해결, 로그인, 기존 수작업 이미지 폴더의 편입(후속 `import` 명령으로 남김).

## 2. 원칙

- **열람만 한다.** 스크롤과 팝업 닫기 외에 클릭·폼 입력·가입·베팅·다운로드를 하지 않는다.
- **정상 사이트는 예의를 지킨다.** `hard_negative`·`normal` 라벨은 robots.txt를 따르고 요청 간격 5초를 둔다. `gambling`·`embedded_banner`는 도메인당 최대 5페이지, 3초 간격으로 발자국을 최소화한다.
- **수집 데이터는 저장소 밖에 둔다.** 결과물은 `/Users/seongmin/Downloads/논문 관련/dataset/` 아래에 쓰고, 저장소에는 코드와 시드 CSV만 들어간다.
- **사람이 한 번 검토한다.** 자동 발견(discover)은 후보 파일에만 쓰고, 캡처(capture)는 사용자가 확정한 시드 파일만 읽는다.

## 3. 구성

Python 3.12 패키지 `src/crawler/`. 실행은 저장소 루트에서 `python -m crawler <명령>`.

| 모듈 | 책임 |
|---|---|
| `__main__.py` | argparse CLI. 세 명령 `discover`, `capture`, `stats` |
| `config.py` | `Settings` 데이터클래스. 기본값 + `.env` + CLI 인자 순으로 덮어씀 |
| `domains.py` | 등록 도메인 추출(tldextract), 솔트 섞은 sha256 해시 12자리, URL 정규화 |
| `seeds.py` | 시드 CSV 읽기·쓰기, 등록 도메인 기준 중복 제거, 플랫폼 제외 목록 |
| `browser.py` | Playwright 컨텍스트 팩토리: 기기 프로필, 요청 차단, 팝업·다이얼로그·다운로드 처리 |
| `blocked.py` | 차단 안내 페이지 판정 (순수 함수) |
| `banners.py` | 페이지 안 요소 목록에서 배너 후보를 고르는 필터 (순수 함수) + 브라우저에서 요소 목록을 뽑는 JS 문자열 |
| `capture.py` | 페이지 1개 처리 파이프라인과 도메인 순회 |
| `discover.py` | 커뮤니티 링크 수집, DuckDuckGo 검색 결과 수집 |
| `store.py` | 경로 규칙, `meta.jsonl`·`index.jsonl` 추가 기록, 재실행 판단, 퍼셉추얼 해시 중복 제거 |
| `stats.py` | index 집계 |

순수 함수(`blocked`, `banners` 필터, `domains`, `seeds` 파싱)는 브라우저 없이 단위 테스트한다.

## 4. 명령과 입력

### 시드 파일 `seeds/*.csv`

컬럼 `url,source,added_at,note`. 라벨별 파일: `gambling.csv`, `embedded_banner.csv`, `hard_negative.csv`, `normal.csv`. 자동 발견 결과는 `candidates.csv`에만 쌓이고, 사용자가 검토해 `gambling.csv`로 옮긴다. `keywords.txt`는 검색 키워드 한 줄에 하나(기본 10개 동봉: 토토사이트, 안전놀이터, 카지노사이트, 메이저사이트, 바카라사이트, 슬롯사이트, 먹튀검증, 스포츠토토 사이트 추천, 파워볼사이트, 온라인카지노). `blocklist.txt`는 어떤 경우에도 열지 않을 도메인.

플랫폼 제외 목록(코드에 고정): naver.com, google.com, kakao.com, daum.net, youtube.com, facebook.com, instagram.com, twitter.com, x.com, t.me, telegram.org, tistory.com, blogspot.com, wikipedia.org, apple.com, microsoft.com, cloudflare.com.

### `discover community --seeds seeds/community_lists.csv [--out seeds/candidates.csv]`

각 커뮤니티 페이지를 열어 모든 `a[href]`를 모으고, 페이지 도메인과 다른 등록 도메인만 남긴 뒤 플랫폼 제외 목록과 기존 시드 전체에 없는 것을 `candidates.csv`에 `source=community:<페이지 도메인>`으로 추가한다.

### `discover search [--keywords seeds/keywords.txt] [--per-keyword 20] [--out seeds/candidates.csv]`

`https://html.duckduckgo.com/html/?q=<키워드>&kl=kr-kr`를 열어 결과 링크(`a.result__a`)의 `uddg` 리다이렉트 파라미터를 풀어 실제 URL을 얻는다. 키워드당 상위 N개, 질의 간 3초 간격, `source=search:<키워드>`. 구글·네이버는 자동화 접근을 막으므로 쓰지 않는다.

### `capture --label <라벨> --seeds seeds/<라벨>.csv [--per-domain 4] [--max-domains 300] [--out <루트>] [--emit-candidates] [--concurrency 3]`

시드의 도메인마다 홈페이지를 캡처하고, 같은 등록 도메인의 내부 링크를 `per-domain - 1`개 골라 순서대로 캡처한다. 내부 링크는 href에 이벤트·공지·casino·sports·slot·event·notice가 들어간 것을 우선하고, 없으면 처음 나온 순서로 고른다. `--emit-candidates`를 주면 배너 후보 중 외부 도메인으로 나가는 href의 등록 도메인을 `candidates.csv`에 `source=banner:<페이지 도메인>`으로 추가한다. `embedded_banner` 수집에 이 플래그를 함께 쓰는 것이 "배너 추적" 시드 경로다.

### `stats [--out <루트>]`

`index.jsonl`을 읽어 라벨별 도메인 수, 페이지 수(ok/blocked_kr/error/duplicate), 배너 크롭 수를 표로 출력한다.

## 5. 캡처 규칙

### 브라우저

- Playwright 헤드리스 Chromium, 기기 프로필 `Pixel 7`(412×915, DPR 2, Android Chrome UA), 로케일 `ko-KR`, 타임존 `Asia/Seoul`.
- 컨텍스트 옵션: `accept_downloads=False`, `ignore_https_errors=True`. `media`·`font` 요청은 차단하고, `image`는 허용한다(배너가 이미지이므로).
- 다이얼로그(alert/confirm/prompt/beforeunload)는 즉시 dismiss, 새로 열리는 페이지(팝업)는 즉시 닫는다.
- 동시 컨텍스트 3개. 도메인별 최소 간격은 `gambling`·`embedded_banner` 3초, `hard_negative`·`normal` 5초. 후자는 `urllib.robotparser`로 robots.txt를 확인해 불허 경로는 건너뛴다.

### 페이지 1개 처리 순서

1. `goto(url, wait_until="domcontentloaded", timeout=20s)`. 타임아웃이면 1회 재시도, 다시 실패하면 `status=error`.
2. 최종 URL과 본문으로 차단 판정(6절). 차단이면 `status=blocked_kr`로 기록하고 종료.
3. 네트워크 유휴를 최대 5초 기다린 뒤, 페이지 끝까지 뷰포트 높이 단위로 스크롤해 지연 로딩을 깨우고 맨 위로 돌아와 1.5초 대기.
4. 전체 페이지 스크린샷 저장(`full_page=True`, PNG). 높이가 15,000px을 넘으면 그 높이까지만 자른다.
5. 배너 후보 추출(아래)과 요소 스크린샷 저장.
6. 내부 링크 수집(홈페이지에서만).
7. 퍼셉추얼 해시(16×16 average hash)를 계산해 같은 도메인의 기존 `ok` 페이지와 해밍 거리 5 이하이면 `status=duplicate`로 기록하고 방금 저장한 파일을 지운다.
8. `meta.jsonl`과 `index.jsonl`에 한 줄 추가.

### 배너 후보

브라우저에서 `img`, `a`, `iframe`, `[style*="background-image"]` 요소의 페이지 좌표 bbox(스크롤 보정), 표시 여부, `src`/`currentSrc`, 가장 가까운 조상 `a`의 `href`, 태그명을 JSON으로 뽑는다. Python 필터는 다음을 통과한 것만 남긴다.

- 표시 중이고 CSS px 기준 너비 150 이상, 높이 40 이상, 면적 12,000 이상
- 가로세로비 0.2~8
- 다른 후보와 IoU 0.8 이상이면 면적이 큰 쪽만 유지
- 면적 내림차순 상위 12개
- `embedded_banner` 라벨에서는 href의 등록 도메인이 페이지 도메인과 다른 후보만

각 후보는 `element.screenshot()`으로 PNG 저장. 요소가 스크린샷 시점에 사라졌으면 그 후보만 건너뛴다.

## 6. 차단 페이지 판정

다음 중 하나면 `blocked_kr`.

- 최종 URL의 호스트가 `warning.or.kr` 또는 `www.warning.or.kr`
- 본문 텍스트에 "불법·유해정보(사이트)에 대한 차단 안내" 또는 "방송통신심의위원회"와 "차단"이 함께 있음

이 판정은 `(final_url, body_text) -> bool` 순수 함수다. 국내 망에서는 이 비율이 높을 수 있으며 우회는 범위 밖이다. `stats`가 라벨별 차단 비율을 보여 준다.

## 7. 저장 규격

기본 루트 `/Users/seongmin/Downloads/논문 관련/dataset/`. 우선순위는 CLI `--out` > `.env`의 `CRAWLER_OUT` > 기본값. 기존 `도박 사이트 이미지/` 폴더와 PDF는 건드리지 않는다.

```
dataset/
  index.jsonl                         # 전역, 페이지당 1줄
  gambling/
    3f9a1c2b7d4e/                     # 도메인 해시 12자리
      meta.jsonl                      # 이 도메인의 페이지들
      20260923T203512_0_full.png      # 시각(KST)_페이지순번_full
      20260923T203512_0_b0.png        # 배너 크롭 k번
      20260923T203512_0_b1.png
  embedded_banner/ ...
  hard_negative/ ...
  normal/ ...
```

도메인 해시 = `sha256(salt + 등록도메인)[:12]`. 솔트는 저장소 `.env`의 `CRAWLER_SALT`(git 제외, `.env.example` 동봉). 솔트가 없으면 실행을 거부한다. 원본 도메인은 메타에 함께 저장하되, 공개용 내보내기에서는 해시만 남길 수 있게 한다.

메타 한 줄 예:

```json
{"id": "3f9a1c2b7d4e_20260923T203512_0", "label": "gambling", "seed_source": "community:example-verify.com",
 "url": "https://example-toto.com/", "final_url": "https://example-toto.com/main", "domain": "example-toto.com",
 "domain_hash": "3f9a1c2b7d4e", "captured_at": "2026-09-23T20:35:12+09:00", "status": "ok",
 "viewport": {"width": 412, "height": 915, "dpr": 2}, "title": "...", "full_path": "gambling/3f9a1c2b7d4e/20260923T203512_0_full.png",
 "page_height": 4380, "phash": "a3f0...", "banners": [
   {"path": "gambling/3f9a1c2b7d4e/20260923T203512_0_b0.png", "bbox": [0, 812, 412, 96], "tag": "img",
    "src": "https://cdn.example/banner1.gif", "href": "https://other-site.com/", "href_domain": "other-site.com", "external": true}
 ], "error": null}
```

`status` 값: `ok`, `blocked_kr`, `error`, `duplicate`, `robots_disallow`. `error`일 때 `error`에 예외 종류와 메시지를 넣는다. 경로는 루트 기준 상대 경로로 저장해 폴더를 옮겨도 깨지지 않게 한다.

### 재실행

시작 시 `index.jsonl`을 읽어 도메인별 `ok` 페이지 수를 세고, `per-domain`을 채운 도메인은 건너뛴다. 정규화한 URL(fragment와 utm_* 제거)이 7일 안에 캡처된 기록이 있으면 건너뛴다. 중단 후 다시 실행하면 이어서 진행된다.

## 8. 오류 처리

- 페이지 단위로 예외를 잡아 `status=error`로 기록하고 다음으로 넘어간다. 도메인 전체가 DNS 실패면 홈 1건만 기록하고 내부 링크는 시도하지 않는다.
- 브라우저 프로세스가 죽으면 컨텍스트를 새로 만들고 해당 도메인을 1회 재시도한다.
- `Ctrl+C`는 현재 페이지 기록을 마친 뒤 종료한다. 진행 상황은 `index.jsonl`에 이미 있으므로 별도 상태 파일은 두지 않는다.
- 실행 끝에 라벨별 ok/blocked/error/duplicate 요약을 출력한다.

## 9. 테스트

`tests/` 아래 pytest.

- 단위: `domains`(등록 도메인 추출·해시·URL 정규화), `seeds`(CSV 파싱·중복 제거·플랫폼 제외), `blocked`(URL·본문 조합별 판정), `banners` 필터(크기·비율·IoU·상위 N·외부 링크 조건), `store`(경로 생성·재실행 판단·해밍 거리).
- 통합: `tests/fixtures/`에 가짜 도박 홈페이지(배너 이미지 3개, 내부 링크 2개, 외부 링크 1개)와 가짜 차단 안내 페이지 HTML을 두고, 테스트가 `http.server`를 임시 포트로 띄운 뒤 실제 Playwright로 `capture`를 돌려 full·banner PNG와 `index.jsonl` 줄이 생기는지, 차단 페이지가 `blocked_kr`로 기록되는지 확인한다. 임시 디렉터리를 출력 루트로 쓴다.
- 실제 도박 사이트나 외부 네트워크에 의존하는 테스트는 두지 않는다.

## 10. 환경과 의존성

- Python 3.12, 저장소 안 `.venv`(이미 `.gitignore`에 있음). `requirements.txt`: `playwright`, `tldextract`, `Pillow`, `pytest`.
- 설치: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium`.
- `.env.example`에 `CRAWLER_OUT`, `CRAWLER_SALT`를 둔다.
- `seeds/` 아래 라벨별 빈 CSV(헤더만)와 `keywords.txt`, `blocklist.txt`, 시드 작성법을 적은 `README.md`를 동봉한다. 커뮤니티·중계·웹툰 사이트 URL은 사용자가 채운다.

## 11. 윤리·법적 고려

- 도박 사이트 접근은 화면 열람에 한하며 어떤 상호작용도 하지 않는다. 스크린샷에 운영자 연락처(텔레그램 ID 등)가 포함될 수 있으나 이용자 개인정보는 수집하지 않는다.
- 수집 원본은 배포하지 않고, 공개는 해시·라벨·특징 벡터·OCR 텍스트 수준으로 한다(배경조사 보고서의 데이터 공개 방침과 일치).
- 정상 사이트 수집은 robots.txt와 요청 간격을 지키고, 공개 페이지만 대상으로 한다.
- 연구윤리 절차 필요 여부는 지도교수와 확인한다(디자인 개요서 메일에서 질의한 항목).

## 12. 후속 작업(이 스펙 밖)

- `import`: 기존 `도박 사이트 이미지/` 14장을 `gambling` 라벨로 편입하면서 메타를 생성.
- 라벨링 기준서와 라벨링 도구 연결, OCR 텍스트 추출.
- 공개용 내보내기(해시·라벨·특징만).
