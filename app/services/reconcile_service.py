"""Loads a merchant's ledger, runs the reconciliation engine, persists matches, statuses and alerts."""
from sqlmodel import Session, select

from app.engine.reconcile import CreditNoteIn, InvoiceIn, PaymentIn, ReconcileResult, SupplierRef, reconcile
from app.models import Alert, CreditNote, InvoiceRow, Match, PaymentOut, Supplier
from app.services import alert_service

AUTO_CONFIRM_AT = 0.9


def reconcile_merchant(session: Session, merchant_id: int) -> ReconcileResult:
    suppliers = list(session.exec(select(Supplier).where(Supplier.merchant_id == merchant_id)).all())
    invoices = list(session.exec(select(InvoiceRow).where(
        InvoiceRow.merchant_id == merchant_id, InvoiceRow.confirmed == True,  # noqa: E712
        InvoiceRow.supplier_id != None, InvoiceRow.bill_type.in_(["gst_invoice", "kachcha"]))).all())  # noqa: E711
    payments = list(session.exec(select(PaymentOut).where(
        PaymentOut.merchant_id == merchant_id, PaymentOut.category == "supplier",
        PaymentOut.confirmed == True)).all())  # noqa: E712
    inv_ids = [i.id for i in invoices]

    _drop_auto_matches(session, inv_ids)
    kept = list(session.exec(select(Match).where(Match.invoice_id.in_(inv_ids))).all()) if inv_ids else []
    inv_applied = _sum_by(kept, "invoice_id")
    pay_applied = _sum_by([m for m in kept if m.payment_id], "payment_id")
    notes = list(session.exec(select(CreditNote).where(CreditNote.merchant_id == merchant_id)).all())

    result = reconcile(
        [InvoiceIn(i.id, i.supplier_id, i.invoice_no, i.invoice_date, i.grand_total, inv_applied.get(i.id, 0.0))
         for i in invoices],
        [PaymentIn(p.id, p.amount, p.paid_at.date(), p.supplier_id, p.payee_name, p.payee_vpa, p.remark,
                   pay_applied.get(p.id, 0.0)) for p in payments],
        [SupplierRef(s.id, s.name, tuple(s.aliases), s.payee_vpa) for s in suppliers],
        [CreditNoteIn(n.id, n.supplier_id, n.amount, n.status, n.against_invoice_id) for n in notes
         if n.status in ("expected", "received", "applied")],  # applied notes are re-applied on every run
    )
    _persist(session, merchant_id, invoices, notes, inv_applied, result)
    return result


def _drop_auto_matches(session: Session, invoice_ids: list[int]) -> None:
    if not invoice_ids:
        return
    for m in session.exec(select(Match).where(Match.invoice_id.in_(invoice_ids), Match.method != "manual",
                                              Match.payment_id != None)).all():  # noqa: E711
        session.delete(m)
    session.flush()


def _sum_by(matches: list[Match], attr: str) -> dict[int, float]:
    out: dict[int, float] = {}
    for m in matches:
        out[getattr(m, attr)] = out.get(getattr(m, attr), 0.0) + m.amount_applied
    return out


def _persist(session, merchant_id, invoices, notes, inv_applied, result: ReconcileResult) -> None:
    for m in result.matches:
        session.add(Match(invoice_id=m.invoice_id, payment_id=m.payment_id, amount_applied=m.amount, method=m.method,
                          confidence=m.confidence, confirmed=m.confidence >= AUTO_CONFIRM_AT))
    notes_by_id = {n.id: n for n in notes}
    credit_by_invoice: dict[int, float] = {}
    for ca in result.credit_applications:
        credit_by_invoice[ca.invoice_id] = credit_by_invoice.get(ca.invoice_id, 0.0) + ca.amount
        note = notes_by_id[ca.credit_note_id]
        if note.status == "received":
            note.status = "applied"
            session.add(note)
    new_by_invoice: dict[int, float] = {}
    for m in result.matches:
        new_by_invoice[m.invoice_id] = new_by_invoice.get(m.invoice_id, 0.0) + m.amount
    for inv in invoices:
        inv.amount_settled = round(inv_applied.get(inv.id, 0.0) + new_by_invoice.get(inv.id, 0.0)
                                   + credit_by_invoice.get(inv.id, 0.0), 2)
        if inv.status != "disputed":
            inv.status = result.invoice_status[inv.id]
        session.add(inv)
    alert_service.replace_system_alerts(session, merchant_id, _alerts(merchant_id, result))
    session.flush()


def _alerts(merchant_id: int, result: ReconcileResult) -> list[Alert]:
    out = [Alert(merchant_id=merchant_id, type=a.type, severity=a.severity, invoice_id=a.invoice_id,
                 supplier_id=a.supplier_id, message_en=a.message_en, message_hi=a.message_hi) for a in result.alerts]
    for f in result.fuzzy_suggestions:
        out.append(Alert(merchant_id=merchant_id, type="confirm_payee", severity="info", supplier_id=f.supplier_id,
                         payment_id=f.payment_id,
                         message_en="A payment went to an unfamiliar payee name that looks like one of your suppliers. Confirm?",
                         message_hi="Ek payment anjaan naam par gaya hai jo aapke supplier jaisa lagta hai. Confirm karein?"))
    return out


def confirm_payee(session: Session, payment_id: int, supplier_id: int) -> None:
    """Merchant confirms who a payment went to; the name becomes an alias so it resolves next time."""
    pay = session.get(PaymentOut, payment_id)
    sup = session.get(Supplier, supplier_id)
    if pay is None or sup is None or pay.merchant_id != sup.merchant_id:
        raise ValueError("payment and supplier must belong to the same merchant")
    pay.supplier_id = supplier_id
    if pay.payee_name and pay.payee_name not in sup.aliases:
        sup.aliases = [*sup.aliases, pay.payee_name]
    session.add(pay)
    session.add(sup)
    for a in session.exec(select(Alert).where(Alert.payment_id == payment_id, Alert.type == "confirm_payee")).all():
        a.status = "resolved"
        session.add(a)
    session.flush()
    reconcile_merchant(session, pay.merchant_id)
