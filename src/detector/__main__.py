"""python -m detector ocr|embed|evaluate|evidence"""
from __future__ import annotations

import argparse
from pathlib import Path

from .data import load_samples
from .embed import embed_images
from .ocr import run_ocr
from .report import DEFAULT_INDEX, HOME, evaluate


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="detector")
    ap.add_argument("cmd", choices=["ocr", "embed", "evaluate", "evidence", "holdout", "evaluate2"])
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ap.add_argument("--root", type=Path, default=HOME)
    ap.add_argument("--labels", type=Path, default=None, help="evaluate2: 정답 덮어쓰기 CSV")
    ap.add_argument("--cutoff", default=None, help="evaluate2: 시험 기준일(첫 수집일 이상)")
    ap.add_argument("--test-until", default=None, help="evaluate2: 시험 상한일(첫 수집일 이하, 기본 2026-11-18)")
    ap.add_argument("--out", type=Path, default=None, help="evaluate2: 산출물 폴더")
    args = ap.parse_args(argv)
    feats = args.root / "_features"
    if args.cmd == "evaluate2":
        from . import evaluate2 as e2

        evaluate2_index = args.index if args.index != DEFAULT_INDEX else e2.DEFAULT_INDEX
        e2.evaluate2(evaluate2_index, args.root, args.labels or e2.DEFAULT_LABELS,
                     args.cutoff or e2.DEFAULT_CUTOFF, args.out,
                     args.test_until or e2.DEFAULT_TEST_UNTIL)
        print("evaluate2: metrics_v2.{json,md}")
        return
    if args.cmd == "evaluate":
        evaluate(args.index, args.root)
        return
    if args.cmd == "evidence":
        from .evidence import summarize_at_ref, write_reports

        repo = Path(__file__).resolve().parents[2]
        write_reports(summarize_at_ref(args.index, repo, "HEAD"), repo / "docs" / "week11")
        print("evidence: docs/week11/problem_evidence.{json,md}")
        return
    if args.cmd == "holdout":
        from .holdout import run_holdout, write_reports

        repo = Path(__file__).resolve().parents[2]
        res = run_holdout(args.index, feats / "index_snapshot_20261109T1400.jsonl", args.root,
                          feats / "predictions.csv")
        write_reports(res, repo / "docs" / "week11")
        print("holdout: docs/week11/holdout.{json,md}")
        return
    samples = load_samples(args.index, args.root, include_embedded=True)
    if args.cmd == "ocr":
        run_ocr(samples, feats / "ocr")
    else:
        embed_images(samples, feats / "clip")
    print(f"{args.cmd}: {len(samples)} screens")


if __name__ == "__main__":
    main()
