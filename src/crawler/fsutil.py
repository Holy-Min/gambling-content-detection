"""파일 쓰기 보조: 중간에 죽어도 잘린 파일이 남지 않게 임시 파일에 쓴 뒤 교체한다."""
from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """같은 디렉터리의 `<이름>.tmp` 에 쓰고 os.replace 로 교체한다(부모 디렉터리는 만든다)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
