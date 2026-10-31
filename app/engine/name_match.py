"""Fuzzy similarity of business names that ignores generic words ("Traders", "Store", ...)."""
import re

from rapidfuzz import fuzz

GENERIC = {"traders", "trader", "store", "stores", "enterprises", "enterprise", "wholesale", "agencies", "agency",
           "co", "company", "and", "sons", "general", "distributors", "supply", "supplies", "mills", "depot", "house"}


def _tokens(name: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", name.casefold())
    distinctive = [t for t in toks if t not in GENERIC]
    return distinctive or toks


def similarity(a: str, b: str) -> float:
    return fuzz.token_set_ratio(" ".join(_tokens(a)), " ".join(_tokens(b)))


SAME_PARTY_MIN = 90.0


def same_party(a: str, b: str) -> bool:
    """Are these two spellings of one business name the same business? ("SHARMA TRADERS" vs "Sharma Traders", yes;
    "Sharma Traders" vs "Sharma Textiles", no.) Stricter than `similarity`, which is meant for finding candidates."""
    ta, tb = " ".join(sorted(_tokens(a))), " ".join(sorted(_tokens(b)))
    return bool(ta) and fuzz.ratio(ta, tb) >= SAME_PARTY_MIN
