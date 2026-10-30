"""When was each invoice last paid, from either side of the ledger (retailer payment or distributor receipt)."""
from datetime import date

from sqlmodel import Session, select

from app.models import CollectionIn, Match, PaymentOut


def last_payment_dates(session: Session, invoice_ids: list[int]) -> dict[int, date]:
    if not invoice_ids:
        return {}
    matches = list(session.exec(select(Match).where(Match.invoice_id.in_(invoice_ids))).all())
    pay_ids = {m.payment_id for m in matches if m.payment_id}
    col_ids = {m.collection_id for m in matches if m.collection_id}
    pay_dates = {p.id: p.paid_at.date() for p in session.exec(select(PaymentOut).where(PaymentOut.id.in_(pay_ids))).all()} if pay_ids else {}
    col_dates = {c.id: c.received_at.date() for c in session.exec(select(CollectionIn).where(CollectionIn.id.in_(col_ids))).all()} if col_ids else {}
    out: dict[int, date] = {}
    for m in matches:
        d = pay_dates.get(m.payment_id) if m.payment_id else col_dates.get(m.collection_id)
        if d and (m.invoice_id not in out or d > out[m.invoice_id]):
            out[m.invoice_id] = d
    return out
