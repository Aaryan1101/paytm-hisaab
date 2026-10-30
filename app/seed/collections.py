"""Daily UPI collections (merchant's own sales) and non-supplier expenses."""
import random
from datetime import date, datetime, time, timedelta

from sqlmodel import Session

from app.engine import festivals
from app.models import CollectionIn, Merchant, PaymentOut

WEEKDAY_FACTOR = [1.0, 0.6, 0.9, 1.0, 1.1, 1.3, 1.5]  # Mon..Sun: Sunday high, Tuesday low
BASE = 11_000.0
MIN_DAY, MAX_DAY = 8_000.0, 25_000.0
EXPENSE_RANGE = (3_500, 6_500)


def generate_collections(session: Session, rng: random.Random, merchant: Merchant, start: date, end: date) -> None:
    d = start
    while d <= end:
        amount = BASE * WEEKDAY_FACTOR[d.weekday()] * festivals.multiplier(d) * rng.uniform(0.9, 1.1)
        amount = round(max(MIN_DAY, min(MAX_DAY, amount)), 2)
        session.add(CollectionIn(merchant_id=merchant.id, amount=amount, received_at=datetime.combine(d, time(21, 0)),
                                 payer_vpa="customers@upi", mdr_amount=0, net_amount=amount))
        d += timedelta(days=1)


def generate_expenses(session: Session, rng: random.Random, merchant: Merchant, start: date, end: date) -> None:
    d = start
    while d <= end:
        session.add(PaymentOut(merchant_id=merchant.id, amount=float(rng.randint(*EXPENSE_RANGE)),
                               paid_at=datetime.combine(d, time(18, 0)), mode="cash", category="expense",
                               payee_name="Shop expenses", remark="rent, wages, electricity"))
        d += timedelta(days=1)
