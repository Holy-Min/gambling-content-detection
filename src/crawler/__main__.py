"""CLI: python -m crawler discover|capture|stats"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import LABELS, load_settings
from .domains import registrable_domain
from .seeds import load_blocklist, read_seeds, seed_domains
from .stats import format_table, summarize
from .store import Store

SEEDS_DIR = Path("seeds")
ALL_SEED_FILES = [SEEDS_DIR / f"{lab}.csv" for lab in LABELS] + [SEEDS_DIR / "community_lists.csv", SEEDS_DIR / "candidates.csv"]


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
    c.add_argument("--out", default=None, help="저장 루트 (기본: .env CRAWLER_OUT 또는 /Users/seongmin/Downloads/논문 관련/dataset)")
    c.add_argument("--per-domain", type=int, default=None)
    c.add_argument("--max-domains", type=int, default=None)
    c.add_argument("--concurrency", type=int, default=None)
    c.add_argument("--emit-candidates", action="store_true", help="배너의 외부 링크 도메인을 seeds/candidates.csv에 추가")
    c.add_argument("--refresh", action="store_true", help="이미 수집한 도메인도 홈을 다시 열어 충전·가입 등 내부 페이지를 추가 수집")
    c.add_argument("--click-menus", action="store_true", help="홈의 충전·입금·가입 메뉴(버튼·JS 링크)를 클릭해 결제 직전 화면을 추가 수집")
    c.add_argument("--max-menu-clicks", type=int, default=None, help="도메인당 클릭할 메뉴 수 (기본 2)")

    s = sub.add_parser("stats", help="라벨별 수집 현황")
    s.add_argument("--out", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.command == "stats":
        settings = load_settings(out=ns.out)
        print(format_table(summarize(Store(settings.out_root, settings.salt).load_index())))
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
    # capture
    from .capture import run_capture  # playwright import 지연
    settings = load_settings(out=ns.out, per_domain=ns.per_domain, max_domains=ns.max_domains, concurrency=ns.concurrency, refresh=ns.refresh or None,
                             click_menus=ns.click_menus or None, max_menu_clicks=ns.max_menu_clicks)
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
