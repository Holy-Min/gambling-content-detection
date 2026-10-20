from crawler.fsutil import atomic_write_text


def test_atomic_write_creates_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "sub" / "a.txt"
    atomic_write_text(p, "hello\n")
    assert p.read_text(encoding="utf-8") == "hello\n"
    assert not (tmp_path / "sub" / "a.txt.tmp").exists()


def test_atomic_write_replaces_existing(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("old", encoding="utf-8")
    atomic_write_text(p, "새 내용")
    assert p.read_text(encoding="utf-8") == "새 내용" and list(tmp_path.iterdir()) == [p]
