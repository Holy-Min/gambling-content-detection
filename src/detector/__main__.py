"""python -m detector ocr|embed|evaluate|evidence|holdout|evaluate2|compare-image"""
from __future__ import annotations

import argparse
from pathlib import Path

from .data import load_samples
from .embed import embed_images, embed_with
from .ocr import run_ocr
from .report import DEFAULT_INDEX, HOME, evaluate


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="detector")
    ap.add_argument("cmd", choices=["ocr", "embed", "evaluate", "evidence", "holdout", "evaluate2", "compare-image"])
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ap.add_argument("--root", type=Path, default=HOME)
    ap.add_argument("--labels", type=Path, default=None, help="evaluate2·compare-image·embed: 정답 덮어쓰기 CSV")
    ap.add_argument("--cutoff", default=None, help="evaluate2: 시험 기준일(첫 수집일 이상)")
    ap.add_argument("--test-until", default=None, help="evaluate2: 시험 상한일(첫 수집일 이하, 기본 2026-11-18)")
    ap.add_argument("--out", type=Path, default=None, help="evaluate2: 산출물 폴더")
    ap.add_argument("--encoder", default=None, help="embed: 특징 추출기 키(없으면 기존 CLIP)")
    ap.add_argument("--encoders", default=None, help="compare-image: 쉼표로 나눈 키(기본 clip-b32,siglip2-b16,mobileclip2-s2)")
    ap.add_argument("--image-encoder", default="clip-b32", help="evaluate2: 이미지 특징 추출기 키(기본 clip-b32)")
    ap.add_argument("--fp-budget", type=float, default=0.01, help="evaluate2·compare-image: 이미지로 건지는 판정의 오탐 예산")
    args = ap.parse_args(argv)
    feats = args.root / "_features"
    if args.cmd == "evaluate2":
        from . import evaluate2 as e2

        from .embed import ENCODERS

        if args.image_encoder not in ENCODERS:
            ap.error(f"unknown encoder {args.image_encoder}; choose from {', '.join(ENCODERS)}")
        evaluate2_index = args.index if args.index != DEFAULT_INDEX else e2.DEFAULT_INDEX
        e2.evaluate2(evaluate2_index, args.root, args.labels or e2.DEFAULT_LABELS,
                     args.cutoff or e2.DEFAULT_CUTOFF, args.out,
                     args.test_until or e2.DEFAULT_TEST_UNTIL, args.image_encoder, args.fp_budget)
        print(f"evaluate2: {e2.output_names(args.image_encoder)['json']} (+ .md)")
        return
    if args.cmd == "compare-image":
        from . import compare_image as ci
        from .embed import DEFAULT_COMPARE_ENCODERS, ENCODERS

        keys = args.encoders.split(",") if args.encoders else list(DEFAULT_COMPARE_ENCODERS)
        bad = [k for k in keys if k not in ENCODERS]
        if bad:
            ap.error(f"unknown encoder {bad}; choose from {', '.join(ENCODERS)}")
        from . import evaluate2 as e2

        ci.compare_image(args.index if args.index != DEFAULT_INDEX else e2.DEFAULT_INDEX, args.root,
                         args.labels or e2.DEFAULT_LABELS, args.cutoff or e2.DEFAULT_CUTOFF, args.out,
                         args.test_until or e2.DEFAULT_TEST_UNTIL, keys, args.fp_budget)
        print("compare-image: image_compare.{json,md}")
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
    samples = load_samples(args.index, args.root, include_embedded=True, labels_path=args.labels)
    if args.cmd == "ocr":
        run_ocr(samples, feats / "ocr")
    elif args.encoder:
        embed_with(samples, feats, args.encoder)
    else:
        embed_images(samples, feats / "clip")
    print(f"{args.cmd}: {len(samples)} screens")


if __name__ == "__main__":
    main()
