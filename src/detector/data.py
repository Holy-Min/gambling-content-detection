"""index.jsonl 적재와 첫 화면 크롭."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

POSITIVE = {"gambling"}
NEGATIVE = {"hard_negative", "normal"}
EMBEDDED = "embedded_banner"
LEGAL = "legal_gambling"
EXCLUDE = "exclude"
OVERRIDE_LABELS = {"gambling", "hard_negative", "normal", EMBEDDED, LEGAL, EXCLUDE}


@dataclass(frozen=True)
class Sample:
    id: str
    label: str
    y: int | None
    domain: str
    domain_hash: str
    page_kind: str | None
    image_path: Path
    captured_at: str = ""


def load_label_overrides(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """정답 덮어쓰기 CSV(unit,key,label,...) → (site_map[domain_hash], screen_map[id])."""
    site_map: dict[str, str] = {}
    screen_map: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            unit = (row.get("unit") or "").strip()
            key = (row.get("key") or "").strip()
            label = (row.get("label") or "").strip()
            if unit not in ("site", "screen"):
                raise ValueError(f"{path}:{n}: unit must be site|screen, got {unit!r}")
            if not key:
                raise ValueError(f"{path}:{n}: empty key")
            if label not in OVERRIDE_LABELS:
                raise ValueError(f"{path}:{n}: invalid label {label!r}")
            (site_map if unit == "site" else screen_map)[key] = label
    return site_map, screen_map


def load_samples(
    index_path: Path,
    dataset_root: Path,
    include_embedded: bool = False,
    labels_path: Path | None = None,
) -> list[Sample]:
    site_map, screen_map = load_label_overrides(labels_path) if labels_path else ({}, {})
    samples: list[Sample] = []
    with Path(index_path).open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") != "ok" or not row.get("full_path"):
                continue
            label = screen_map.get(row["id"]) or site_map.get(row["domain_hash"]) or row["label"]
            if label in POSITIVE:
                y = 1
            elif label in NEGATIVE:
                y = 0
            elif label in (EMBEDDED, LEGAL) and include_embedded:
                y = None
            else:
                continue
            samples.append(
                Sample(
                    id=row["id"],
                    label=label,
                    y=y,
                    domain=row["domain"],
                    domain_hash=row["domain_hash"],
                    page_kind=row.get("page_kind"),
                    image_path=Path(dataset_root) / row["full_path"],
                    captured_at=row.get("captured_at") or "",
                )
            )
    return samples


def first_screen(path: Path, height: int = 1830) -> Image.Image:
    """PNG 상단 `height`px 를 RGB 로 반환. 더 짧으면 있는 만큼."""
    with Image.open(path) as im:
        im = im.convert("RGBA") if im.mode in ("P", "LA") or "transparency" in im.info else im
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        else:
            im = im.convert("RGB")
        return im.crop((0, 0, im.width, min(height, im.height)))
