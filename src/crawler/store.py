"""저장 경로 규칙, meta/index JSONL 기록, 재실행 판단, 퍼셉추얼 해시."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from .domains import domain_hash, normalize_url

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def ts_label(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def ahash(path: Path, size: int = 16) -> str:
    im = Image.open(path).convert("L").resize((size, size), Image.Resampling.LANCZOS)
    px = list(im.tobytes())
    avg = sum(px) / len(px)
    bits = "".join("1" if p > avg else "0" for p in px)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class Store:
    def __init__(self, root: Path, salt: str):
        self.root = Path(root)
        self.salt = salt
        self.index_path = self.root / "index.jsonl"
        self._index: list[dict] = self.load_index()

    def hash_of(self, domain: str) -> str:
        return domain_hash(domain, self.salt)

    def domain_dir(self, label: str, domain: str) -> Path:
        return self.root / label / self.hash_of(domain)

    def load_index(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        rows = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def record(self, meta: dict) -> None:
        d = self.domain_dir(meta["label"], meta["domain"])
        d.mkdir(parents=True, exist_ok=True)
        line = json.dumps(meta, ensure_ascii=False)
        with (d / "meta.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.root.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._index.append(meta)

    def ok_count(self, label: str, domain: str) -> int:
        return sum(1 for m in self._index if m["label"] == label and m["domain"] == domain and m["status"] == "ok")

    def seen_recently(self, url: str, days: int = 7, now: datetime | None = None) -> bool:
        now = now or now_kst()
        target = normalize_url(url)
        for m in self._index:
            if m.get("url_norm") != target:
                continue
            at = datetime.fromisoformat(m["captured_at"])
            if now - at <= timedelta(days=days):
                return True
        return False

    def find_duplicate(self, label: str, domain: str, phash: str, threshold: int = 5) -> str | None:
        for m in self._index:
            if m["label"] == label and m["domain"] == domain and m["status"] == "ok" and m.get("phash"):
                if hamming(m["phash"], phash) <= threshold:
                    return m["id"]
        return None
