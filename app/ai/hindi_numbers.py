"""Parses spoken or typed amounts: "paanch hazaar", "ek lakh baarah hazaar", "5,000", "₹3k", "five thousand"."""
import re

_UNITS = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4, "paanch": 5, "panch": 5,
    "five": 5, "chhe": 6, "chah": 6, "chhah": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8, "nau": 9, "nine": 9,
    "das": 10, "ten": 10, "gyarah": 11, "barah": 12, "baarah": 12, "twelve": 12, "terah": 13, "chaudah": 14, "pandrah": 15,
    "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19, "bees": 20, "twenty": 20, "tees": 30, "thirty": 30, "chalis": 40,
    "forty": 40, "pachas": 50, "fifty": 50, "saath": 60, "sixty": 60, "sattar": 70, "seventy": 70, "assi": 80, "eighty": 80,
    "nabbe": 90, "ninety": 90,
}
_MULTIPLIERS = {"sau": 100, "hundred": 100, "hazaar": 1_000, "hajar": 1_000, "thousand": 1_000, "lakh": 100_000, "lac": 100_000}
_HALF = {"dedh": 1.5, "dhai": 2.5, "adhai": 2.5}
_DIGITS = re.compile(r"(?:₹|rs\.?|rupees?)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakh|lac|hazaar|hajar|thousand|k)?", re.I)


def parse_amount(text: str) -> float | None:
    m = _DIGITS.search(text)
    if m:
        value = float(m.group(1).replace(",", ""))
        mult = (m.group(2) or "").lower()
        return value * {"lakh": 100_000, "lac": 100_000, "hazaar": 1_000, "hajar": 1_000, "thousand": 1_000, "k": 1_000}.get(mult, 1)
    return _parse_words(text.lower())


def _parse_words(text: str) -> float | None:
    total, current, seen = 0.0, 0.0, False
    for tok in re.findall(r"[a-z]+", text):
        if tok in _UNITS:
            current, seen = current + _UNITS[tok], True
        elif tok in _HALF:
            current, seen = _HALF[tok], True
        elif tok in _MULTIPLIERS and seen:
            mult = _MULTIPLIERS[tok]
            if mult == 100:
                current = (current or 1) * 100
            else:
                total, current = total + (current or 1) * mult, 0.0
        elif seen and tok not in ("rupaye", "rupees", "rs", "ka", "ke", "ki"):
            break  # number phrase ended
    return (total + current) if seen else None
