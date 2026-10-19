"""CLI: python -m crawler discover|capture|stats|nightly|explore|promote"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import LABELS, load_settings
from .domains import registrable_domain
from .seeds import all_seed_files, load_blocklist, read_seeds, seed_domains
from .stats import format_table, summarize
from .store import Store, now_kst

SEEDS_DIR = Path("seeds")
ALL_SEED_FILES = all_seed_files(SEEDS_DIR)
STAGE_CHOICES = ("search", "community", "explore", "capture")


def today_kst() -> str:
    return now_kst().date().isoformat()


def _stage_list(text: str) -> list[str]:
    out = [s.strip() for s in text.split(",") if s.strip()]
    bad = [s for s in out if s not in STAGE_CHOICES]
    if bad:
        raise argparse.ArgumentTypeError(f"알 수 없는 단계 {bad}. 가능: {', '.join(STAGE_CHOICES)}")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crawler", description="도박 화면 데이터셋 수집기")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="시드 후보 수집 → seeds/candidates.csv")
    dk = d.add_subparsers(dest="kind", required=True)
    dc = dk.add_parser("community", help="검증 커뮤니티 페이지의 외부 링크 수집")
    dc.add_argument("--seeds", default=str(SEEDS_DIR / "community_lists.csv"))
    dc.add_argument("--out", default=str(SEEDS_DIR / "candidates.csv"))
    ds = dk.add_parser("search", help="Yahoo 검색 결과 수집")
    ds.add_argument("--keywords", default=str(SEEDS_DIR / "keywords.txt"))
    ds.add_argument("--per-keyword", type=int, default=20)
    ds.add_argument("--out", default=str(SEEDS_DIR / "candidates.csv"))

    c = sub.add_parser("capture", help="시드 파일의 도메인을 캡처")
    c.add_argument("--label", required=True, choices=LABELS)
    c.add_argument("--seeds", required=True)
    c.add_argument("--out", default=None, help="저장 루트 (기본: .env CRAWLER_OUT 또는 /Users/seongmin/datasets/gambling)")
    c.add_argument("--per-domain", type=int, default=None)
    c.add_argument("--max-domains", type=int, default=None)
    c.add_argument("--concurrency", type=int, default=None)
    c.add_argument("--emit-candidates", action="store_true", help="배너의 외부 링크 도메인을 seeds/candidates.csv에 추가")
    c.add_argument("--refresh", action="store_true", help="이미 수집한 도메인도 홈을 다시 열어 충전·가입 등 내부 페이지를 추가 수집")
    c.add_argument("--click-menus", action="store_true", help="홈의 충전·입금·가입 메뉴(버튼·JS 링크)를 클릭해 결제 직전 화면을 추가 수집")
    c.add_argument("--max-menu-clicks", type=int, default=None, help="도메인당 클릭할 메뉴 수 (기본 2)")
    c.add_argument("--recapture-days", type=int, default=None, help="이 일수 안에 찍은 화면은 다시 찍지 않는다 (기본 7, 야간 루프 1)")

    s = sub.add_parser("stats", help="라벨별 수집 현황")
    s.add_argument("--out", default=None)
    s.add_argument("--review", action="store_true", help="본 데이터셋 대신 리뷰 루트(_review)를 집계")

    n = sub.add_parser("nightly", help="야간 루프: search → community → explore → capture → 보고서")
    n.add_argument("--date", default=None, help="YYYY-MM-DD (기본 오늘 KST)")
    n.add_argument("--out-dir", default="out", help="보고서 루트 (out/<날짜>/)")
    n.add_argument("--only", type=_stage_list, default=None, help="이 단계만 (쉼표 구분)")
    n.add_argument("--skip", type=_stage_list, default=None, help="이 단계는 건너뜀 (쉼표 구분)")
    n.add_argument("--budget-min", type=int, default=90, help="전체 예산(분)")
    n.add_argument("--recapture-days", type=int, default=1)
    n.add_argument("--max-candidates", type=int, default=None, help="선캡처 후보 상한 (기본 40)")
    n.add_argument("--dry-run", action="store_true", help="계획만 출력")

    e = sub.add_parser("explore", help="후보 선캡처 + review.csv + 키워드 확장만 실행")
    e.add_argument("--date", default=None)
    e.add_argument("--out-dir", default="out")
    e.add_argument("--max-candidates", type=int, default=None)
    e.add_argument("--per-domain", type=int, default=None, help="후보 도메인당 페이지 수 (기본 2)")

    pr = sub.add_parser("promote", help="review.csv 의 verdict 를 시드·데이터셋에 반영")
    pr.add_argument("review_csv")
    pr.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.command == "stats":
        settings = load_settings(out=ns.out)
        root = settings.review_root if ns.review else settings.out_root
        print(format_table(summarize(Store(root, settings.salt).load_index())))
        return 0
    if ns.command == "discover":
        from .discover import discover_community, discover_search  # playwright import 지연
        settings = load_settings()
        known = seed_domains(ALL_SEED_FILES)
        if ns.kind == "community":
            n = asyncio.run(discover_community(settings, Path(ns.seeds), Path(ns.out), known))
        else:
            n = asyncio.run(discover_search(settings, Path(ns.keywords), Path(ns.out), known, ns.per_keyword))
        print(f"후보 {n}개 추가 → {ns.out}. 검토 후 seeds/gambling.csv로 옮기세요.")
        return 0
    if ns.command == "nightly":
        from .nightly import Runner, acquire_lock, release_lock
        settings = load_settings(recapture_days=ns.recapture_days, nightly_max_candidates=ns.max_candidates)
        today = ns.date or today_kst()
        runner = Runner(settings, seeds_dir=SEEDS_DIR, out_base=Path(ns.out_dir), today=today, only=ns.only, skip=ns.skip,
                        budget_min=ns.budget_min, dry_run=ns.dry_run)
        if ns.dry_run:
            print(runner.dry_run_plan())
            return 0
        lock = Path(ns.out_dir) / ".lock"
        if not acquire_lock(lock):
            print(f"이미 실행 중입니다: {lock}")
            return 2
        try:
            return asyncio.run(runner.run())
        finally:
            release_lock(lock)
    if ns.command == "explore":
        from .explore import run_explore
        settings = load_settings(nightly_candidate_pages=ns.per_domain)
        today = ns.date or today_kst()
        res = asyncio.run(run_explore(settings, seeds_dir=SEEDS_DIR, out_dir=Path(ns.out_dir) / today, today=today, max_candidates=ns.max_candidates))
        print(json.dumps({"precaptured": res.precaptured, "auto_communities": res.auto_communities, "keywords_added": res.keywords_added,
                          "keywords_retired": res.keywords_retired, "review_csv": str(res.review_csv), **res.capture_summary}, ensure_ascii=False, indent=2))
        return 0
    if ns.command == "promote":
        from .promote import run_promote
        return run_promote(Path(ns.review_csv), load_settings(), SEEDS_DIR, today=today_kst(), dry_run=ns.dry_run)
    # capture
    from .capture import run_capture  # playwright import 지연
    settings = load_settings(out=ns.out, per_domain=ns.per_domain, max_domains=ns.max_domains, concurrency=ns.concurrency, refresh=ns.refresh or None,
                             click_menus=ns.click_menus or None, max_menu_clicks=ns.max_menu_clicks, recapture_days=ns.recapture_days)
    blocklist = load_blocklist(SEEDS_DIR / "blocklist.txt")
    seeds = [s for s in read_seeds(Path(ns.seeds)) if registrable_domain(s.url) not in blocklist]
    if not seeds:
        print(f"시드가 없습니다: {ns.seeds}")
        return 1
    print(f"[{ns.label}] 도메인 {len(seeds)}개, 저장 루트 {settings.out_root}")
    summary = asyncio.run(run_capture(settings, seeds, label=ns.label, emit_candidates=ns.emit_candidates,
                                      candidates_path=SEEDS_DIR / "candidates.csv",
                                      known_domains=frozenset(seed_domains(ALL_SEED_FILES))))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
