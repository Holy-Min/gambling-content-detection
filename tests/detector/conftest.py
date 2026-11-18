"""구 .venv(크롤러 전용)에는 numpy·sklearn 이 없으므로 detector 테스트 수집을 건너뛴다."""
from importlib.util import find_spec

collect_ignore_glob = (
    [] if all(find_spec(m) for m in ("numpy", "sklearn")) else ["test_*.py"]
)
