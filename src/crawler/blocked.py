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


# Cloudflare 등 봇 확인 페이지와 지역 차단 안내 페이지. 화면에 도박 콘텐츠가 없으므로 ok로 세지 않는다.
CHALLENGE_MARKERS = ("잠시만 기다리십시오", "Just a moment", "Checking your browser", "Verify you are human",
                     "Attention Required", "cf-chl", "challenge-platform", "사람인지 확인", "보안 확인 중")
GEOBLOCK_MARKERS = ("법적 사유로 이용 불가", "not available in your country", "not available in your region",
                    "restricted in your jurisdiction", "unavailable in your location", "접속이 제한된 지역")


def is_challenge_page(title: str, body_text: str) -> bool:
    text = f"{title or ''}\n{body_text or ''}"
    return any(m.lower() in text.lower() for m in CHALLENGE_MARKERS + GEOBLOCK_MARKERS)
