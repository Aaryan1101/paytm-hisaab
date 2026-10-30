"""IMS suggestions for regular-GST merchants. Approving writes to our DB only; live filing needs a GSP."""
from dataclasses import dataclass

from sqlmodel import Session, select

from app.engine import ims as engine
from app.models import Alert, CreditNote, ImsEntry, InvoiceRow, Merchant, Supplier
from app.services import alert_service
from app.services.errors import Invalid, NotApplicable, NotFound

ALERT_TYPES = ("gstin_risk", "missing_from_ims")


@dataclass(frozen=True)
class ImsReport:
    month: str
    entries: list[ImsEntry]
    missing: list[tuple[InvoiceRow, engine.MissingFromIms]]

    def counts(self) -> dict[str, int]:
        out = {"accept": 0, "reject": 0, "pending": 0}
        for e in self.entries:
            out[e.action or "pending"] += 1
        return out


def get_ims(session: Session, merchant_id: int, month: str) -> ImsReport:
    merchant = session.get(Merchant, merchant_id)
    if merchant is None:
        raise NotFound("Merchant not found")
    if merchant.gst_scheme != "regular":
        raise NotApplicable("IMS applies to regular-GST merchants only")
    entries = list(session.exec(select(ImsEntry).where(ImsEntry.merchant_id == merchant_id, ImsEntry.month == month)
                                .order_by(ImsEntry.id)).all())
    suppliers = list(session.exec(select(Supplier).where(Supplier.merchant_id == merchant_id)).all())
    status_by_gstin = {s.gstin: s.gstin_status for s in suppliers if s.gstin}
    gstin_by_id = {s.id: s.gstin for s in suppliers}
    invoices = [i for i in session.exec(select(InvoiceRow).where(
        InvoiceRow.merchant_id == merchant_id, InvoiceRow.confirmed == True)).all()  # noqa: E712
        if i.supplier_id in gstin_by_id and gstin_by_id[i.supplier_id]]
    in_month = [i for i in invoices if i.invoice_date.strftime("%Y-%m") == month]
    expected_gstins = {gstin_by_id[n.supplier_id] for n in session.exec(select(CreditNote).where(
        CreditNote.merchant_id == merchant_id, CreditNote.status == "expected")).all() if gstin_by_id.get(n.supplier_id)}

    decisions, missing = engine.suggest(
        [engine.ImsEntryIn(e.id, e.supplier_gstin, e.invoice_no, e.taxable, e.tax,
                           status_by_gstin.get(e.supplier_gstin, "active"), e.not_purchased) for e in entries],
        [engine.BillIn(i.id, gstin_by_id[i.supplier_id], i.invoice_no, i.taxable_total, i.tax_total) for i in in_month],
        expected_gstins)
    by_entry = {e.id: e for e in entries}
    for d in decisions:
        e = by_entry[d.entry_id]
        e.itc_risk, e.invoice_id = d.itc_risk_alert, d.bill_id
        if not e.user_override:
            e.action, e.reason_en, e.reason_hi = d.action, d.reason_en, d.reason_hi
        session.add(e)
    missing_pairs = [(next(i for i in in_month if i.id == m.bill_id), m) for m in missing]
    _refresh_alerts(session, merchant_id, entries, missing_pairs)
    session.flush()
    return ImsReport(month, entries, missing_pairs)


def _refresh_alerts(session, merchant_id, entries, missing_pairs) -> None:
    fresh = [Alert(merchant_id=merchant_id, type="gstin_risk", severity="high", message_en=f"{e.supplier_name}: {e.reason_en}",
                   message_hi=f"{e.supplier_name}: {e.reason_hi}", invoice_id=e.invoice_id) for e in entries if e.itc_risk]
    fresh += [Alert(merchant_id=merchant_id, type="missing_from_ims", severity="warn", invoice_id=inv.id,
                    supplier_id=inv.supplier_id, message_en=f"{inv.invoice_no}: {m.reason_en}",
                    message_hi=f"{inv.invoice_no}: {m.reason_hi}") for inv, m in missing_pairs]
    alert_service.replace_system_alerts(session, merchant_id, fresh, ALERT_TYPES)


def override_entry(session: Session, merchant_id: int, entry_id: int, action: str) -> ImsEntry:
    if action not in ("accept", "reject", "pending"):
        raise Invalid("Action must be accept, reject or pending")
    e = session.get(ImsEntry, entry_id)
    if e is None or e.merchant_id != merchant_id:
        raise NotFound("IMS entry not found")
    e.action, e.user_override = action, True
    e.reason_en, e.reason_hi = "Set by you", "Aapne khud set kiya"
    session.add(e)
    session.flush()
    return e


def approve_all(session: Session, merchant_id: int, month: str) -> int:
    """Record the current suggestions as the merchant's decisions (our DB only)."""
    report = get_ims(session, merchant_id, month)
    for e in report.entries:
        e.approved = True
        session.add(e)
        if e.invoice_id:
            inv = session.get(InvoiceRow, e.invoice_id)
            inv.ims_action, inv.ims_reason = e.action, e.reason_en
            session.add(inv)
    session.flush()
    return len(report.entries)
