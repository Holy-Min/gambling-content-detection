"""저장 경로 규칙, meta/index JSONL 기록, 재실행 판단, 퍼셉추얼 해시."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from .domains import domain_hash, normalize_url
from .fsutil import atomic_write_text

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def _day(dt: datetime) -> date:
    """KST 달력 날짜. 재캡처 창은 24시간 슬라이딩이 아니라 이 날짜 차이로 잰다."""
    return dt.astimezone(KST).date()


def _within(at: datetime, now: datetime, days: int) -> bool:
    return (_day(now) - _day(at)).days < days


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

    def ok_count(self, label: str, domain: str, days: int | None = None, now: datetime | None = None) -> int:
        """ok 행 수. days 가 있으면 그 일수 안에 찍은 것만 센다(재캡처 창)."""
        now = now or now_kst()
        n = 0
        for m in self._index:
            if m["label"] != label or m["domain"] != domain or m["status"] != "ok":
                continue
            if days is None or _within(datetime.fromisoformat(m["captured_at"]), now, days):
                n += 1
        return n

    def seen_recently(self, url: str, days: int = 7, now: datetime | None = None) -> bool:
        now = now or now_kst()
        target = normalize_url(url)
        for m in self._index:
            if m.get("url_norm") != target:
                continue
            at = datetime.fromisoformat(m["captured_at"])
            if _within(at, now, days):
                return True
        return False

    def find_duplicate(self, label: str, domain: str, phash: str, threshold: int = 5) -> str | None:
        for m in self._index:
            if m["label"] == label and m["domain"] == domain and m["status"] == "ok" and m.get("phash"):
                if hamming(m["phash"], phash) <= threshold:
                    return m["id"]
        return None

    def rows_for(self, label: str, domain: str) -> list[dict]:
        return [m for m in self._index if m["label"] == label and m["domain"] == domain]

    @staticmethod
    def page_index(meta: dict) -> int:
        """id `<해시>_<시각>_<idx>` 의 idx. 홈은 0. 형식이 다르면 -1."""
        try:
            return int(str(meta.get("id", "")).rsplit("_", 1)[1])
        except (IndexError, ValueError):
            return -1

    def blocked_recently(self, label: str, domain: str, days: int = 7, now: datetime | None = None) -> bool:
        """가장 최근 홈(idx 0) 행이 blocked_kr 이고 days 안이면 참. 같은 망에서 다시 두드려도 결과가 같기 때문에 건너뛴다."""
        now = now or now_kst()
        homes = [m for m in self.rows_for(label, domain) if self.page_index(m) == 0]
        if not homes:
            return False
        last = max(homes, key=lambda m: m["captured_at"])
        return last["status"] == "blocked_kr" and _within(datetime.fromisoformat(last["captured_at"]), now, days)

    def rewrite_index(self) -> None:
        atomic_write_text(self.index_path, "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in self._index))

    def remove_domain(self, label: str, domain: str, delete_files: bool = True) -> int:
        """색인에서 (label, domain) 행을 지우고(파일 다시 씀) 폴더를 삭제한다. 지운 행 수."""
        before = len(self._index)
        self._index = [m for m in self._index if not (m["label"] == label and m["domain"] == domain)]
        removed = before - len(self._index)
        if removed:
            self.rewrite_index()
        d = self.domain_dir(label, domain)
        if delete_files and d.exists():
            shutil.rmtree(d)
        return removed

    def adopt_domain(self, src_dir: Path, rows: list[dict], label: str) -> list[dict]:
        """다른 루트의 도메인 폴더와 행들을 이 루트의 label 아래로 들인다.
        폴더를 옮기고, 행의 label·full_path·banners[].path 접두를 고쳐 meta.jsonl·index.jsonl 에 기록한다. 새 행 목록을 돌려준다."""
        if not rows:
            return []
        domain = rows[0]["domain"]
        dest = self.domain_dir(label, domain)
        old_prefix = f"{rows[0]['label']}/{rows[0]['domain_hash']}/"
        new_prefix = f"{label}/{self.hash_of(domain)}/"
        src_dir = Path(src_dir)
        dest_existed = dest.exists()
        if src_dir.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest_existed:
                for p in src_dir.iterdir():
                    if p.name != "meta.jsonl" and not (dest / p.name).exists():
                        shutil.move(str(p), str(dest / p.name))
                shutil.rmtree(src_dir)
            else:
                shutil.move(str(src_dir), str(dest))
                (dest / "meta.jsonl").unlink(missing_ok=True)   # 옛 라벨 행은 아래서 새로 쓴다

        def fix(path: str | None) -> str | None:
            if path and path.startswith(old_prefix):
                return new_prefix + path[len(old_prefix):]
            return path

        out: list[dict] = []
        for m in rows:
            n = json.loads(json.dumps(m, ensure_ascii=False))
            n["label"] = label
            n["domain_hash"] = self.hash_of(domain)
            n["full_path"] = fix(n.get("full_path"))
            n["banners"] = [{**b, "path": fix(b.get("path"))} for b in (n.get("banners") or [])]
            self.record(n)
            out.append(n)
        return out
