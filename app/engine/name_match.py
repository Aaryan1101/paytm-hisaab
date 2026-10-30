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
