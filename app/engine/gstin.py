import re

_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FORMAT = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")


def check_digit(first14: str) -> str:
    """Mod-36 check character for the first 14 characters of a GSTIN."""
    total = 0
    for i, c in enumerate(first14):
        v = _CHARSET.index(c) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _CHARSET[(36 - total % 36) % 36]


def is_valid(gstin: str) -> bool:
    return bool(_FORMAT.fullmatch(gstin)) and check_digit(gstin[:14]) == gstin[14]


def make(state_code: str, pan: str, entity_no: str = "1") -> str:
    """Build a valid GSTIN from a 2-digit state code, a 10-char PAN and an entity number."""
    body = f"{state_code}{pan}{entity_no}Z"
    return body + check_digit(body)


def state_code(gstin: str) -> str:
    return gstin[:2]
