"""Small merchant-level settings."""
from sqlmodel import Session

from app.models import Merchant
from app.services.errors import NotFound


def set_cash_balance(session: Session, merchant_id: int, amount: float) -> float:
    """The merchant tells us their current cash/bank balance; the forecast starts from it."""
    m = session.get(Merchant, merchant_id)
    if m is None:
        raise NotFound("Merchant not found")
    m.opening_balance = round(amount, 2)
    session.add(m)
    session.flush()
    return m.opening_balance
