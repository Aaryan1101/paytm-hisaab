"""Finds a merchant's supplier from a spoken or typed name."""
from sqlmodel import Session, select

from app.engine.name_match import similarity
from app.models import Supplier

MIN_SCORE = 75.0


def find_supplier(session: Session, merchant_id: int, query: str) -> Supplier | None:
    best: tuple[float, Supplier | None] = (0.0, None)
    for s in session.exec(select(Supplier).where(Supplier.merchant_id == merchant_id)).all():
        score = max(similarity(query, n) for n in (s.name, *s.aliases))
        if score > best[0]:
            best = (score, s)
    return best[1] if best[0] >= MIN_SCORE else None
