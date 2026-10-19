# 야간 루프 운영

매일 04:30 `python -m crawler nightly` 가 search → community → explore → capture 를 돌리고 `out/<날짜>/report.md` 를 쓴다. 설계는 `docs/superpowers/specs/2026-10-19-nightly-seed-exploration-design.md`.

## 설치·해제
```bash
cp scripts/launchd/com.gambling-crawler.nightly.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gambling-crawler.nightly.plist
launchctl kickstart -k gui/$(id -u)/com.gambling-crawler.nightly   # 지금 한 번 실행(검증용)
launchctl bootout gui/$(id -u)/com.gambling-crawler.nightly         # 해제
```
전제: 전원 연결, 잠자기 방지(또는 `sudo pmset repeat wake MTWRFSU 04:25:00`), 가정용 ISP(차단은 `blocked_kr` 로 기록되는 것이 정상). 회사 앱 루프(02:00, 최대 150분)와 겹치지 않게 04:30.

## 아침 루틴
1. `out/<날짜>/report.md` 를 연다. 맨 위 요약 3줄과 "실패·경고" 를 본다.
2. "검토 대기" 표의 썸네일을 보며 `out/<날짜>/review.csv` 의 `verdict` 열을 채운다: `gambling` · `embedded_banner` · `hard_negative` · `normal` · `community` · `exclude` · `blocked`. 비우면 다음에 다시 판단.
3. `.venv/bin/python -m crawler promote out/<날짜>/review.csv --dry-run` 으로 계획을 보고, 맞으면 `--dry-run` 없이 실행한다. 두 번 돌려도 안전하다.
4. 시드 변경(`seeds/*.csv`, `keywords_auto.txt`, `explore_state.json`)은 루프가 커밋하지 않는다. 확인 후 직접 커밋한다.

## 수동 실행
- 전체: `.venv/bin/python -m crawler nightly` (`--dry-run` 으로 계획만, `--only explore` 처럼 단계 선택, `--budget-min 30`)
- 선캡처만: `.venv/bin/python -m crawler explore --max-candidates 10`
- 리뷰 루트 현황: `.venv/bin/python -m crawler stats --review`
- 잠금이 남아 실행이 거부되면(`out/.lock`): 살아 있는 프로세스가 없을 때만 지운다.

## 종료 코드
0 정상 · 1 일부 단계 실패/부분(보고서의 실패 섹션 확인) · 2 실행 불가(`.env`/CRAWLER_SALT 없음, 잠금, 저장 루트 쓰기 불가) · 3 하드 타임아웃(전체 예산 + 15분, 보고서 없이 강제 종료 — `out/launchd.log` 와 `run.log` 확인)
