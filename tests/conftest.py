"""공용 픽스처: 로컬 픽스처 사이트 서버와 빠른 설정."""
import shutil
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from crawler.config import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "site"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    shutil.copytree(FIXTURES, root)
    for name, size, color in [("banner1.png", (720, 180), (220, 30, 30)), ("banner2.png", (720, 240), (30, 30, 220)),
                              ("banner3.png", (600, 200), (30, 160, 30)), ("icon.png", (48, 48), (0, 0, 0))]:
        Image.new("RGB", size, color).save(root / name)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def fast_settings(tmp_path) -> Settings:
    return Settings(out_root=tmp_path / "dataset", salt="test-salt", per_domain=2, concurrency=1,
                    delays={"gambling": 0.0, "embedded_banner": 0.0, "hard_negative": 0.0, "normal": 0.0, "candidate": 0.0})
