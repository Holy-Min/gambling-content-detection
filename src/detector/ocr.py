"""Apple Vision OCR 실행과 캐시 (id 별 JSON)."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .data import Sample, first_screen

SWIFT_SRC = Path(__file__).resolve().parents[2] / "scripts" / "vision_ocr.swift"
BINARY = Path.home() / "datasets" / "gambling" / "_features" / "bin" / "vision_ocr"


def ensure_binary() -> Path:
    """바이너리가 없거나 소스보다 오래됐으면 swiftc -O 로 컴파일."""
    if not BINARY.exists() or BINARY.stat().st_mtime < SWIFT_SRC.stat().st_mtime:
        BINARY.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["swiftc", "-O", str(SWIFT_SRC), "-o", str(BINARY)],
            capture_output=True, check=True,
        )
    return BINARY


def _run_binary(paths: list[Path]) -> list[dict]:
    out = subprocess.run(
        [str(ensure_binary()), *map(str, paths)], capture_output=True, check=True
    )
    return [json.loads(l) for l in out.stdout.decode("utf-8").splitlines() if l.strip()]


def run_ocr(samples: list[Sample], cache_dir: Path, batch: int = 32) -> dict[str, dict]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict] = {}
    todo: list[Sample] = []
    for s in samples:
        f = cache_dir / f"{s.id}.json"
        if f.exists():
            result[s.id] = json.loads(f.read_text(encoding="utf-8"))
        else:
            todo.append(s)
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for s in chunk:
                p = Path(tmp) / f"{s.id}.png"
                first_screen(s.image_path).save(p)
                paths.append(p)
            rows = _run_binary(paths)
        by_stem = {Path(r["path"]).stem: r for r in rows}
        for s in chunk:
            r = by_stem[s.id]
            entry = {
                "text": "\n".join(l["text"] for l in r["lines"]),
                "lines": r["lines"],
                "ms": r["ms"],
            }
            (cache_dir / f"{s.id}.json").write_text(
                json.dumps(entry, ensure_ascii=False), encoding="utf-8"
            )
            result[s.id] = entry
    return result
