"""Renders the WhatsApp reply for a freshly read bill (pure): summary text plus the decision it is waiting for."""
from app.ai.money_format import inr
from app.ai.graph.pending import PendingAction, for_bill
from app.services.ingest_service import IngestResult

MAX_ISSUES = 3


def _short_date(d) -> str:
    return f"{d.day} {d:%b}"


def render(r: IngestResult) -> tuple[str, PendingAction]:
    inv = r.invoice
    gst = inv.tax_total
    lines = ["Bill padh liya ✅",
             f"{r.supplier_name} · Inv #{inv.invoice_no} · {_short_date(inv.invoice_date)}",
             f"{len(inv.line_items)} items · {inr(inv.grand_total)} (GST {inr(gst)})" if inv.bill_type != "kachcha"
             else f"{len(inv.line_items)} items · {inr(inv.grand_total)} · kachcha bill (non-GST)"]
    if inv.due_date:
        lines.append(f"Due: {_short_date(inv.due_date)}")
    if r.duplicate:
        paid = f" aur aapne {inr(r.duplicate.amount)} pay kar diya hai" if r.duplicate.paid_on else ""
        lines.append(f"⚠️ Yeh bill #{r.duplicate.invoice_no} pehle {_short_date(r.duplicate.invoice_date)} ko bhi aaya tha{paid}. Duplicate lag raha hai.")
        return "\n".join(lines), for_bill(r.invoice_id, r.supplier_name, True)
    for issue in [i for i in r.issues if i.code != "possible_duplicate"][:MAX_ISSUES]:
        lines.append(f"⚠️ {issue.message_hi}")
    if "grand_total" in r.low_confidence_fields:
        lines.append(f"Total {inr(inv.grand_total)} sahi hai?")
    return "\n".join(lines), for_bill(r.invoice_id, r.supplier_name, False)
