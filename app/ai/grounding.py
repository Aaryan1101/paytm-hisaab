"""Guard: every sizeable money figure in a reply must come from a tool result (or the user's own message)."""
import json
import re

from app.ai.hindi_numbers import parse_amount

MIN_CHECKED = 1_000.0
REL_TOL, ABS_TOL = 0.02, 500.0  # spoken amounts are rounded, so allow a little slack
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?(?:\s*(?:lakh|lac|hazaar|hajar|k)\b)?(?:\s+\d[\d,]*\s*(?:hazaar|hajar|sau)\b)*", re.I)


def _grounded_numbers(texts: list[str]) -> set[float]:
    out: set[float] = set()
    for t in texts:
        for m in re.findall(r"\d[\d,]*(?:\.\d+)?", t):
            try:
                out.add(float(m.replace(",", "")))
            except ValueError:
                pass
    return out


def _reply_amounts(reply: str) -> list[float]:
    vals = []
    for m in _NUM.finditer(reply):
        v = _spoken_value(m.group(0))
        if v is not None and v >= MIN_CHECKED:
            vals.append(v)
    return vals


def _spoken_value(s: str) -> float | None:
    parts = re.findall(r"\d[\d,]*(?:\.\d+)?\s*(?:lakh|lac|hazaar|hajar|k|sau)?", s, re.I)
    total = 0.0
    for p in parts:
        v = parse_amount(p)
        if v is None:
            return None
        total += v * (100 if re.search(r"sau", p, re.I) and v < 10 else 1)
    return total


def is_grounded(reply: str, tool_results: list[dict], user_text: str = "") -> bool:
    known = _grounded_numbers([json.dumps(r, ensure_ascii=False, default=str) for r in tool_results] + [user_text])
    for amount in _reply_amounts(reply):
        if not any(abs(amount - k) <= max(ABS_TOL, REL_TOL * k) for k in known):
            return False
    return True
