"""Demo controls: reset to seed, and fire live payment events on stage."""
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app import clock
from app.models import CollectionIn
from app.seed.loader import reset_tables, seed_all
from app.services import distributor_service, message_service, payment_recorder, reconcile_service, settlement_service
from app.services.errors import NotFound
from app.services.supplier_lookup import find_supplier


@dataclass(frozen=True)
class SimulatedPayment:
    gross: float
    mdr: float
    net: float
    matched: list[tuple[str, float]]
    retailer_reliability_before: float | None
    retailer_reliability_after: float | None


def reset(session: Session) -> None:
    reset_tables(session)
    seed_all(session)


def _inr(x: float) -> str:
    return f"Rs {x:,.0f}"


def simulate_payment(session: Session, payer_id: int, supplier_name: str = "Sharma Traders", amount: float = 31_500.0,
                     now: datetime | None = None) -> SimulatedPayment:
    """A retailer pays a distributor over UPI: both ledgers reconcile and the distributor's soundbox announces it."""
    today = clock.today()
    sup = find_supplier(session, payer_id, supplier_name)
    if sup is None or sup.linked_merchant_id is None:
        raise NotFound(f"'{supplier_name}' is not a linked distributor of this merchant")
    dist_id = sup.linked_merchant_id
    before = _reliability(session, dist_id, payer_id, today)
    pay = payment_recorder.record_upi_payment(session, payer_id, sup, amount, now or datetime.combine(today, datetime.min.time()))
    reconcile_service.reconcile_merchant(session, payer_id)
    settlement_service.reconcile_distributor(session, dist_id)
    col = session.exec(select(CollectionIn).where(CollectionIn.utr == pay.utr, CollectionIn.merchant_id == dist_id)).one()
    rows = distributor_service.settlements(session, dist_id)
    matched = next(r.matched for r in rows if r.collection_id == col.id)
    message_service.push_event(session, dist_id, f"{_inr(col.amount)} prapt hue")
    return SimulatedPayment(col.amount, col.mdr_amount, col.net_amount, matched, before,
                            _reliability(session, dist_id, payer_id, today))


def simulate_customer_payment(session: Session, merchant_id: int, amount: float = 2_500.0, now: datetime | None = None) -> CollectionIn:
    """A customer pays the merchant's QR: the soundbox chimes."""
    when = now or datetime.combine(clock.today(), datetime.min.time())
    col = CollectionIn(merchant_id=merchant_id, amount=amount, received_at=when, payer_vpa="customer@upi", net_amount=amount)
    session.add(col)
    session.flush()
    message_service.push_event(session, merchant_id, f"{_inr(amount)} prapt hue")
    return col


def _reliability(session: Session, dist_id: int, retailer_id: int, today) -> float | None:
    try:
        return distributor_service.retailer_row(session, dist_id, retailer_id, today).reliability
    except NotFound:
        return None
