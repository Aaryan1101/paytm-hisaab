"""Seed-time wrappers over the payment recorder (dates in, deterministic UTRs)."""
import random
from datetime import date, datetime, time

from sqlmodel import Session

from app.models import PaymentOut, Supplier
from app.services import payment_recorder


def utr(rng: random.Random) -> str:
    return "".join(rng.choices("0123456789", k=12))


def record_upi_payment(session: Session, rng: random.Random, merchant_id: int, supplier: Supplier, amount: float,
                       paid_on: date, remark: str | None = None, payee_name: str | None = None,
                       use_vpa: bool = True) -> PaymentOut:
    return payment_recorder.record_upi_payment(session, merchant_id, supplier, amount, datetime.combine(paid_on, time(11, 0)),
                                               remark, payee_name, use_vpa, utr=utr(rng))


def record_cash_payment(session: Session, merchant_id: int, supplier: Supplier, amount: float, paid_on: date) -> PaymentOut:
    return payment_recorder.record_cash_payment(session, merchant_id, supplier, amount, datetime.combine(paid_on, time(12, 0)))
