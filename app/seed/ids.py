"""Fake-but-valid identifiers for seed data. GSTINs pass our own checksum; none belong to real firms."""
import random
import string

from app.engine import gstin


def random_pan(rng: random.Random) -> str:
    return ("".join(rng.choices(string.ascii_uppercase, k=5)) + "".join(rng.choices(string.digits, k=4))
            + rng.choice(string.ascii_uppercase))


def new_gstin(rng: random.Random, state_code: str = "09") -> str:
    return gstin.make(state_code, random_pan(rng))


def vpa_for(name: str) -> str:
    slug = "".join(c for c in name.lower() if c.isalnum())[:14]
    return f"{slug}@paytm"


def phone(rng: random.Random) -> str:
    return "9" + "".join(rng.choices(string.digits, k=9))
