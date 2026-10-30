"""A supplier's ledger: bills, payments and credit notes on one timeline with a running balance."""
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from app.models import Alert, CreditNote, InvoiceRow, Match, PaymentOut, Supplier


@dataclass(frozen=True)
class LedgerEntry:
    day: date
    kind: str  # bill | payment | credit_note
    ref: str
    amount: float  # bills positive, payments and credit notes negative
    balance: float
    status: str | None = None


@dataclass(frozen=True)
class SupplierLedger:
    supplier_id: int
    supplier_name: str
    entries: list[LedgerEntry]
    balance_due: float
    open_issues: list[Alert]


def supplier_ledger(session: Session, merchant_id: int, supplier_id: int) -> SupplierLedger | None:
    sup = session.get(Supplier, supplier_id)
    if sup is None or sup.merchant_id != merchant_id:
        return None
    invoices = list(session.exec(select(InvoiceRow).where(
        InvoiceRow.merchant_id == merchant_id, InvoiceRow.supplier_id == supplier_id,
        InvoiceRow.confirmed == True)).all())  # noqa: E712
    inv_ids = [i.id for i in invoices]
    paid_ids = {m.payment_id for m in session.exec(select(Match).where(Match.invoice_id.in_(inv_ids))).all()
                if m.payment_id} if inv_ids else set()
    payments = [p for p in session.exec(select(PaymentOut).where(PaymentOut.merchant_id == merchant_id)).all()
                if p.confirmed and (p.supplier_id == supplier_id or p.id in paid_ids)]
    notes = list(session.exec(select(CreditNote).where(CreditNote.merchant_id == merchant_id,
                                                       CreditNote.supplier_id == supplier_id,
                                                       CreditNote.status.in_(["received", "applied"]))).all())
    rows = ([(i.invoice_date, 0, "bill", i.invoice_no, i.grand_total, i.status) for i in invoices]
            + [(p.paid_at.date(), 1, "payment", p.mode.upper(), -p.amount, None) for p in payments]
            + [(n.created_on or date.min, 2, "credit_note", f"CN-{n.id}", -n.amount, n.status) for n in notes])
    rows.sort(key=lambda r: (r[0], r[1]))
    balance, entries = 0.0, []
    for day, _o, kind, ref, amount, status in rows:
        balance = round(balance + amount, 2)
        entries.append(LedgerEntry(day, kind, ref, amount, balance, status))
    issues = list(session.exec(select(Alert).where(Alert.merchant_id == merchant_id, Alert.supplier_id == supplier_id,
                                                   Alert.status == "open")).all())
    due = round(sum(i.grand_total - i.amount_settled for i in invoices if i.status in ("open", "part_paid")), 2)
    return SupplierLedger(supplier_id, sup.name, entries, due, issues)
