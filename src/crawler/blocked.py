"""국내 망의 불법 사이트 차단 안내 페이지(warning.or.kr) 판정."""
from __future__ import annotations

from .domains import host_of

BLOCKED_HOSTS = frozenset({"warning.or.kr", "www.warning.or.kr"})
_NOTICE = "불법·유해정보(사이트)에 대한 차단 안내"
_KCSC = "방송통신심의위원회"


def is_blocked_kr(final_url: str, body_text: str) -> bool:
    if host_of(final_url) in BLOCKED_HOSTS:
        return True
    text = body_text or ""
    if _NOTICE in text:
        return True
    return _KCSC in text and "차단" in text
