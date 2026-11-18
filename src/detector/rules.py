"""합법 사행 상표 낱말 규칙. 글자(OCR text)에 낱말이 하나라도 있으면 켜진다."""
from __future__ import annotations

# 짧은 낱말은 공백을 지운 글자에서 다른 낱말 안에 걸려서 뺐고(예: country, 환경정보), 로고를 잘못 읽는 화면은 화면에 늘 나오는 상품 낱말로 잡는다.
LEGAL_BRAND_TERMS: tuple[str, ...] = (
    "베트맨", "betman", "프로토승부식", "프로토기록식", "구매투표지",
    "스포츠토토", "sportstoto", "동행복권", "dhlottery",
    "한국마사회", "렛츠런", "letsrun", "kcycle", "kboat",
    "와이즈토토", "wisetoto", "powerball", "엔트리파워볼",
    "세븐럭", "sevenluck", "seven luck", "호이아나", "hoiana",
    "강원랜드", "하이원",
)


def normalize(text: str) -> str:
    """소문자로 바꾸고 모든 공백(전각 포함)을 지운다."""
    return "".join(text.lower().split())


def legal_brand_hits(text: str, terms: tuple[str, ...] = LEGAL_BRAND_TERMS) -> list[str]:
    """글자에 들어 있는 낱말(입력 순서). 정규화 결과가 같은 낱말은 먼저 나온 하나만 센다."""
    norm = normalize(text)
    seen: set[str] = set()
    hits: list[str] = []
    for t in terms:
        nt = normalize(t)
        if nt and nt not in seen and nt in norm:
            seen.add(nt)
            hits.append(t)
    return hits


def legal_rule(text: str, terms: tuple[str, ...] = LEGAL_BRAND_TERMS) -> bool:
    return bool(legal_brand_hits(text, terms))
