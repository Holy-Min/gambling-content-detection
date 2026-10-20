"""review.csv 판정 반영: 시드 추가, 리뷰 폴더를 본 데이터셋으로 이동(라벨·경로 재기록), candidates.csv note 갱신. 두 번 돌려도 안전하다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import CANDIDATE_LABEL, LABELS, Settings
from .domains import registrable_domain
from .review import VERDICTS, ReviewRow, read_review_csv
from .seeds import append_seed, read_rows, remove_domain, update_notes, update_source
from .store import Store

SKIP, PROMOTE, COMMUNITY, EXCLUDE, BLOCKED, DONE = "skip", "promote", "community", "exclude", "blocked", "already"


@dataclass
class Action:
    row: ReviewRow
    kind: str
    detail: str


def plan_promotion(rows: list[ReviewRow]) -> list[Action]:
    bad = [(i + 2, r.verdict) for i, r in enumerate(rows) if r.verdict not in VERDICTS]   # +2: 헤더 다음이 2행
    if bad:
        raise ValueError("허용되지 않은 verdict: " + ", ".join(f"{n}행 '{v}'" for n, v in bad))
    out: list[Action] = []
    for r in rows:
        if r.verdict == "":
            out.append(Action(r, SKIP, "판정 없음"))
        elif r.review_dir and not Path(r.review_dir).exists():
            out.append(Action(r, DONE, "리뷰 폴더 없음(이미 처리됨)"))
        elif r.verdict in LABELS:
            out.append(Action(r, PROMOTE, f"seeds/{r.verdict}.csv 추가 + 폴더를 {r.verdict}/ 로 이동"))
        elif r.verdict == "community":
            out.append(Action(r, COMMUNITY, "community_lists.csv 추가(있으면 source 갱신) + 리뷰 삭제"))
        elif r.verdict == "exclude":
            out.append(Action(r, EXCLUDE, "리뷰 삭제 + candidates note 'excluded'"))
        else:
            out.append(Action(r, BLOCKED, "리뷰 삭제 + candidates note 'blocked_kr'"))
    return out


def apply_promotion(actions: list[Action], settings: Settings, seeds_dir: Path, today: str) -> dict[str, int]:
    seeds_dir = Path(seeds_dir)
    review = Store(settings.review_root, settings.salt)
    main = Store(settings.out_root, settings.salt)
    candidates = seeds_dir / "candidates.csv"
    community = seeds_dir / "community_lists.csv"
    counts = {k: 0 for k in (SKIP, PROMOTE, COMMUNITY, EXCLUDE, BLOCKED, DONE)}
    for a in actions:
        r = a.row
        counts[a.kind] += 1
        if a.kind == SKIP:
            continue
        if a.kind == DONE:
            # 중간에 죽은 이전 실행의 잔여물 정리: 리뷰 색인 행 제거 + 아직 미갱신인 note 채움
            review.remove_domain(CANDIDATE_LABEL, r.domain)
            current = {registrable_domain(c["url"]): c.get("note", "") for c in read_rows(candidates)}.get(r.domain)
            if current is not None and (current.startswith("review:") or current == "unverified"):
                update_notes(candidates, {r.domain: _note_for(r, today)})
            continue
        if a.kind == PROMOTE:
            append_seed(seeds_dir / f"{r.verdict}.csv", r.url, source=f"review:{today}", note=r.note or "nightly 승격", added_at=today)
            rows = review.rows_for(CANDIDATE_LABEL, r.domain)
            if rows:
                main.adopt_domain(review.domain_dir(CANDIDATE_LABEL, r.domain), rows, r.verdict)
                review.remove_domain(CANDIDATE_LABEL, r.domain)
            else:
                print(f"[promote] {r.domain}: 리뷰 행이 없어 폴더를 그대로 둠")
        elif a.kind == COMMUNITY:
            if not append_seed(community, r.url, source=f"review:{today}", note=r.note or "검토 승인", added_at=today):
                update_source(community, r.domain, f"review:{today}")
            review.remove_domain(CANDIDATE_LABEL, r.domain)
        elif a.kind == EXCLUDE:
            review.remove_domain(CANDIDATE_LABEL, r.domain)
        else:
            review.remove_domain(CANDIDATE_LABEL, r.domain)
        if a.kind != COMMUNITY:
            _drop_auto_community(community, r.domain)
        update_notes(candidates, {r.domain: _note_for(r, today)})   # 행마다 즉시 기록(재실행 안전)
    return counts


def _drop_auto_community(community: Path, domain: str) -> None:
    """커뮤니티가 아니라는 판정이면 자동 등록(source=auto:)된 커뮤니티 행을 되돌린다. 사람이 넣은 행은 건드리지 않는다."""
    if any(registrable_domain(c["url"]) == domain and c["source"].startswith("auto:") for c in read_rows(community)):
        remove_domain(community, domain)


def _note_for(r: ReviewRow, today: str) -> str:
    """판정에 대응하는 candidates.csv note 문자열."""
    if r.verdict in LABELS:
        return f"→ {r.verdict}.csv (review {today})"
    if r.verdict == "community":
        return f"→ community_lists.csv (review {today})"
    if r.verdict == "exclude":
        return f"excluded: {r.note or '검토 제외'}"
    return f"blocked_kr {today}"


def run_promote(csv_path: Path, settings: Settings, seeds_dir: Path, *, today: str, dry_run: bool = False) -> int:
    rows = read_review_csv(csv_path)
    try:
        actions = plan_promotion(rows)
    except ValueError as e:
        print(f"거부: {e}")
        return 1
    for a in actions:
        print(f"[{a.kind}] {a.row.domain} verdict={a.row.verdict or '-'} — {a.detail}")
    if dry_run:
        print("(dry-run: 아무것도 바꾸지 않았습니다)")
        return 0
    counts = apply_promotion(actions, settings, seeds_dir, today)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    return 0
