"""Matches the engine was not sure about (confidence below 0.9), and the merchant's "Confirm?" tap."""
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app.models import CollectionIn, InvoiceRow, Match, Merchant, PaymentOut, Supplier
from app.services import settlement_service
from app.services.errors import NotFound


@dataclass(frozen=True)
class PendingMatch:
    match_id: int
    invoice_id: int
    invoice_no: str
    counterparty: str  # supplier (retailer side) or payer (distributor side)
    amount: float
    method: str
    confidence: float
    when: datetime


def pending_for_merchant(session: Session, merchant_id: int) -> list[PendingMatch]:
    """Payment-to-bill matches on this merchant's own ledger that still need a tap."""
    out = []
    rows = session.exec(select(Match, InvoiceRow, PaymentOut).join(InvoiceRow, Match.invoice_id == InvoiceRow.id)
                        .join(PaymentOut, Match.payment_id == PaymentOut.id)
                        .where(InvoiceRow.merchant_id == merchant_id, Match.confirmed == False)  # noqa: E712
                        .order_by(Match.confidence, Match.id)).all()
    names = {s.id: s.name for s in session.exec(select(Supplier).where(Supplier.merchant_id == merchant_id)).all()}
    for m, inv, pay in rows:
        out.append(PendingMatch(m.id, inv.id, inv.invoice_no, names.get(inv.supplier_id, "?"), m.amount_applied, m.method, m.confidence, pay.paid_at))
    return out


def pending_for_distributor(session: Session, distributor_id: int) -> list[PendingMatch]:
    """Receipt-to-bill matches the distributor should confirm."""
    inv_ids = {i.id: i for i in settlement_service.distributor_invoices(session, distributor_id)}
    if not inv_ids:
        return []
    names = {m.id: m.name for m in session.exec(select(Merchant)).all()}
    out = []
    for m, col in session.exec(select(Match, CollectionIn).join(CollectionIn, Match.collection_id == CollectionIn.id)
                               .where(Match.invoice_id.in_(list(inv_ids)), Match.confirmed == False)  # noqa: E712
                               .order_by(Match.confidence, Match.id)).all():
        inv = inv_ids[m.invoice_id]
        out.append(PendingMatch(m.id, inv.id, inv.invoice_no, names.get(col.payer_merchant_id, "?"), m.amount_applied, m.method, m.confidence, col.received_at))
    return out


def confirm(session: Session, match_id: int, allowed_invoice_ids: set[int]) -> Match:
    """Confirming turns the match into a manual one, which re-running reconciliation will never undo."""
    m = session.get(Match, match_id)
    if m is None or m.invoice_id not in allowed_invoice_ids:
        raise NotFound("Match not found")
    m.confirmed, m.method = True, "manual"
    session.add(m)
    session.flush()
    return m


def confirm_for_merchant(session: Session, merchant_id: int, match_id: int) -> Match:
    mine = {i for i in session.exec(select(InvoiceRow.id).where(InvoiceRow.merchant_id == merchant_id)).all()}
    m = session.get(Match, match_id)
    if m is not None and m.payment_id is None:
        raise NotFound("Match not found")  # receipt-side matches belong to the distributor
    return confirm(session, match_id, mine)


def confirm_for_distributor(session: Session, distributor_id: int, match_id: int) -> Match:
    m = session.get(Match, match_id)
    if m is not None and m.collection_id is None:
        raise NotFound("Match not found")  # the retailer's own payment matches are not the distributor's to confirm
    return confirm(session, match_id, {i.id for i in settlement_service.distributor_invoices(session, distributor_id)})
