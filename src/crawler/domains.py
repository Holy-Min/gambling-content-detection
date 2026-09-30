"""등록 도메인 추출, 도메인 해시, URL 정규화."""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

# suffix_list_urls=() → 네트워크 없이 패키지에 내장된 공개 접미사 목록만 사용
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "igshid"}


def _with_scheme(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        return "http://" + url
    return url


def host_of(url: str) -> str:
    return (urlsplit(_with_scheme(url)).hostname or "").lower()


def registrable_domain(url: str) -> str:
    ext = _EXTRACT(_with_scheme(url))
    if ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return host_of(url)  # IP, localhost, 알 수 없는 TLD: 호스트 전체를 그대로 쓴다


def domain_hash(domain: str, salt: str) -> str:
    return hashlib.sha256((salt + domain).encode("utf-8")).hexdigest()[:12]


def normalize_url(url: str) -> str:
    parts = urlsplit(_with_scheme(url))
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))
