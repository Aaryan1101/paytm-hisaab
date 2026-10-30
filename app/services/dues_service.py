"""What a merchant owes suppliers, by period."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import InvoiceRow, Supplier

PERIOD_DAYS = {"today": 0, "week": 6, "month": 30}


@dataclass(frozen=True)
class DueItem:
    supplier_id: int
    supplier_name: str
    amount: float
    next_due: date
    invoice_nos: list[str]


@dataclass(frozen=True)
class Dues:
    period: str
    items: list[DueItem]
    total: float


def remaining(inv: InvoiceRow) -> float:
    return round(inv.grand_total - inv.amount_settled, 2)


def open_invoices(session: Session, merchant_id: int) -> list[InvoiceRow]:
    return list(session.exec(select(InvoiceRow).where(
        InvoiceRow.merchant_id == merchant_id, InvoiceRow.confirmed == True,  # noqa: E712
        InvoiceRow.status.in_(["open", "part_paid"]), InvoiceRow.supplier_id != None,  # noqa: E711
        InvoiceRow.bill_type.in_(["gst_invoice", "kachcha"]))).all())


def get_dues(session: Session, merchant_id: int, today: date, period: str = "week",
             supplier_id: int | None = None) -> Dues:
    until = today + timedelta(days=PERIOD_DAYS[period])
    names = {s.id: s.name for s in session.exec(select(Supplier).where(Supplier.merchant_id == merchant_id)).all()}
    groups: dict[int, list[InvoiceRow]] = {}
    for inv in open_invoices(session, merchant_id):
        if inv.due_date and inv.due_date <= until and (supplier_id is None or inv.supplier_id == supplier_id):
            groups.setdefault(inv.supplier_id, []).append(inv)
    items = [DueItem(sid, names[sid], round(sum(remaining(i) for i in invs), 2), min(i.due_date for i in invs),
                     [i.invoice_no for i in invs]) for sid, invs in groups.items()]
    items.sort(key=lambda x: (x.next_due, -x.amount))
    return Dues(period, items, round(sum(i.amount for i in items), 2))
