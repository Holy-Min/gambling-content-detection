from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from detector import ocr
from detector.data import Sample

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"


def _sample(tmp_path: Path, sid: str, text: str | None) -> Sample:
    im = Image.new("RGB", (824, 600), "white")
    if text:
        ImageDraw.Draw(im).text((40, 200), text, fill="black", font=ImageFont.truetype(FONT, 72))
    p = tmp_path / f"{sid}.png"
    im.save(p)
    return Sample(sid, "gambling", 1, "d.example", "h", None, p)


def test_vision_ocr_reads_korean(tmp_path):
    s = _sample(tmp_path, "a", "첫 충전 보너스 100%")
    res = ocr.run_ocr([s], tmp_path / "cache")
    assert "충전" in res["a"]["text"]
    assert res["a"]["ms"] > 0


def test_ocr_cache_resume(tmp_path, monkeypatch):
    s1 = _sample(tmp_path, "a", "첫 충전 보너스 100%")
    s2 = _sample(tmp_path, "b", "첫 충전 보너스 100%")
    cache = tmp_path / "cache"
    ocr.run_ocr([s1], cache)
    assert (cache / "a.json").exists()
    seen: list[str] = []
    orig = ocr._run_binary

    def spy(paths):
        seen.extend(Path(p).stem for p in paths)
        return orig(paths)

    monkeypatch.setattr(ocr, "_run_binary", spy)
    res = ocr.run_ocr([s1, s2], cache)
    assert seen == ["b"]
    assert set(res) == {"a", "b"}


def test_blank_image_gives_empty_text(tmp_path):
    s = _sample(tmp_path, "w", None)
    res = ocr.run_ocr([s], tmp_path / "cache")
    assert res["w"]["text"] == ""
