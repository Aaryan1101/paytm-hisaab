"""Pass 5: explain the gap left on part-paid invoices with a credit note, or flag it as missing."""
from app.engine.reconcile.state import CLOSE, State
from app.engine.reconcile.types import AlertOut, CreditApplication, CreditNoteIn

SHORT_PAY_MAX_SHARE = 0.10  # gaps up to 10% of the bill look like a short payment, bigger ones like a partial


def run(state: State, credit_notes: list[CreditNoteIn]) -> None:
    used: set[int] = set(state.credit_used)  # notes the linked-credit pass already applied
    for inv in state.invoices.values():
        gap = state.inv_left[inv.id]
        paid_something = gap < inv.total - CLOSE
        if gap <= CLOSE or not paid_something:
            continue
        note = _find_note(inv.id, inv.supplier_id, gap, credit_notes, used)
        if note:
            used.add(note.id)
            state.credit_applications.append(CreditApplication(note.id, inv.id, gap))
            state.inv_left[inv.id] = 0.0
            if note.status == "expected":
                state.alerts.append(_missing_note_alert(inv.id, inv.supplier_id, gap, note.id))
        elif gap / inv.total <= SHORT_PAY_MAX_SHARE:
            state.alerts.append(_missing_note_alert(inv.id, inv.supplier_id, gap, None))


def _find_note(invoice_id, supplier_id, gap, notes, used) -> CreditNoteIn | None:
    fits = [n for n in notes if n.id not in used and n.status in ("expected", "received")
            and n.supplier_id == supplier_id and abs(n.amount - gap) <= CLOSE]
    fits.sort(key=lambda n: n.against_invoice_id != invoice_id)  # prefer a note tied to this invoice
    return fits[0] if fits else None


def _missing_note_alert(invoice_id, supplier_id, gap, note_id) -> AlertOut:
    return AlertOut(
        type="missing_credit_note", severity="warn", supplier_id=supplier_id, invoice_id=invoice_id,
        amount=round(gap, 2), credit_note_id=note_id,
        message_en=f"Short payment of Rs {gap:,.0f}: the credit note has not been issued. Ask the supplier.",
        message_hi=f"Rs {gap:,.0f} kam pay hua hai; credit note abhi tak nahi aaya. Supplier se maangein.",
    )
