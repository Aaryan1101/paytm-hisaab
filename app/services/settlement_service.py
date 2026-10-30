"""Distributor-side reconciliation of UPI receipts to invoices, matching on the gross amount (MDR shown separately)."""
from sqlmodel import Session, select

from app.engine.reconcile import InvoiceIn, PaymentIn, reconcile
from app.models import CollectionIn, InvoiceRow, Match, PaymentOut, Supplier
from app.services.reconcile_service import AUTO_CONFIRM_AT, _sum_by


def distributor_invoices(session: Session, distributor_id: int) -> list[InvoiceRow]:
    return list(session.exec(select(InvoiceRow).join(Supplier, InvoiceRow.supplier_id == Supplier.id).where(
        Supplier.linked_merchant_id == distributor_id, InvoiceRow.confirmed == True,  # noqa: E712
        InvoiceRow.bill_type.in_(["gst_invoice", "kachcha"]))).all())


def reconcile_distributor(session: Session, distributor_id: int) -> None:
    """Match receipts that have no retailer-side payment record (those are matched by the retailer's own ledger)."""
    invoices = distributor_invoices(session, distributor_id)
    inv_ids = [i.id for i in invoices]
    if not inv_ids:
        return
    dropped: dict[int, float] = {}  # collection-based amounts being recomputed, per invoice
    for m in session.exec(select(Match).where(Match.invoice_id.in_(inv_ids), Match.collection_id != None)).all():  # noqa: E711
        dropped[m.invoice_id] = dropped.get(m.invoice_id, 0.0) + m.amount_applied
        session.delete(m)
    session.flush()
    kept = list(session.exec(select(Match).where(Match.invoice_id.in_(inv_ids))).all())
    applied = _sum_by(kept, "invoice_id")
    paired_utrs = {u for u in session.exec(select(PaymentOut.utr).where(PaymentOut.utr != None)).all()}  # noqa: E711
    collections = [c for c in session.exec(select(CollectionIn).where(
        CollectionIn.merchant_id == distributor_id, CollectionIn.payer_merchant_id != None)).all()  # noqa: E711
        if c.utr not in paired_utrs]
    result = reconcile(
        [InvoiceIn(i.id, i.merchant_id, i.invoice_no, i.invoice_date, i.grand_total, applied.get(i.id, 0.0))
         for i in invoices],
        [PaymentIn(c.id, c.amount, c.received_at.date(), supplier_id=c.payer_merchant_id) for c in collections], [])
    new = {}
    for m in result.matches:
        session.add(Match(invoice_id=m.invoice_id, collection_id=m.payment_id, amount_applied=m.amount, method=m.method,
                          confidence=m.confidence, confirmed=m.confidence >= AUTO_CONFIRM_AT))
        new[m.invoice_id] = new.get(m.invoice_id, 0.0) + m.amount
    for inv in invoices:
        if inv.id not in new and inv.id not in dropped:
            continue  # settled through the retailer's own ledger (payments, credit notes): leave it alone
        inv.amount_settled = round(inv.amount_settled - dropped.get(inv.id, 0.0) + new.get(inv.id, 0.0), 2)
        inv.status = "paid" if inv.grand_total - inv.amount_settled <= 0.5 else (
            "part_paid" if inv.amount_settled > 0.5 else "open")
        session.add(inv)
    session.flush()
