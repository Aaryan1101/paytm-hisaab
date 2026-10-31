"""What happens to a bill after it has been read: confirm with corrections, or discard."""
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from app.models import Alert, InvoiceRow
from app.services import reconcile_service
from app.services.errors import Invalid, NotFound

CORRECTABLE = {"invoice_no": str, "invoice_date": date, "due_date": date, "grand_total": float, "taxable_total": float,
               "tax_total": float}


def _get(session: Session, merchant_id: int, invoice_id: int) -> InvoiceRow:
    inv = session.get(InvoiceRow, invoice_id)
    if inv is None or inv.merchant_id != merchant_id:
        raise NotFound("Invoice not found")
    return inv


def _resolve_alerts(session: Session, invoice_id: int, types: tuple[str, ...]) -> None:
    for a in session.exec(select(Alert).where(Alert.invoice_id == invoice_id, Alert.status == "open",
                                              Alert.type.in_(types))).all():
        a.status = "resolved"
        session.add(a)


def confirm_invoice(session: Session, merchant_id: int, invoice_id: int, corrections: dict | None = None) -> InvoiceRow:
    inv = _get(session, merchant_id, invoice_id)
    for field, value in (corrections or {}).items():
        if field not in CORRECTABLE:
            raise Invalid(f"Field '{field}' cannot be corrected")
        setattr(inv, field, date.fromisoformat(value) if CORRECTABLE[field] is date and isinstance(value, str) else value)
    inv.confirmed = True
    if inv.status == "disputed":
        inv.status = "open"
    session.add(inv)
    _resolve_alerts(session, inv.id, ("possible_duplicate",))
    session.flush()
    reconcile_service.reconcile_merchant(session, merchant_id)
    return inv


def discard_invoice(session: Session, merchant_id: int, invoice_id: int) -> InvoiceRow:
    inv = _get(session, merchant_id, invoice_id)
    inv.confirmed, inv.status = False, "disputed"
    session.add(inv)
    _resolve_alerts(session, inv.id, ("possible_duplicate", "gstin_invalid", "total_mismatch"))
    session.flush()
    return inv


@dataclass(frozen=True)
class AccuracyStats:
    accuracy: float | None  # share of key fields the merchant left unchanged; None until a read bill has been confirmed
    bills: int
    fields: int


def extraction_stats(session: Session, merchant_id: int | None = None) -> AccuracyStats:
    """Raw extraction vs what the merchant confirmed: the accuracy number for the pitch slide."""
    q = select(InvoiceRow).where(InvoiceRow.confirmed == True)  # noqa: E712
    if merchant_id:
        q = q.where(InvoiceRow.merchant_id == merchant_id)
    same = total = bills = 0
    for inv in session.exec(q).all():
        if not inv.raw_json:
            continue  # seeded or hand-entered bills have no raw extraction to compare
        bills += 1
        for field in ("invoice_no", "grand_total", "taxable_total", "tax_total"):
            raw = inv.raw_json.get(field)
            if raw is None:
                continue
            total += 1
            same += abs(float(raw) - float(getattr(inv, field))) < 0.005 if field != "invoice_no" else raw == inv.invoice_no
    return AccuracyStats(same / total if total else None, bills, total)


def extraction_accuracy(session: Session, merchant_id: int | None = None) -> float | None:
    return extraction_stats(session, merchant_id).accuracy
