"""Pass 0: credit notes that have arrived and name a bill reduce what is owed on it, whether or not it was paid.

Reconciliation recomputes everything from scratch on each run, so received *and* already-applied notes are re-applied
every time (applying them once and forgetting would silently re-open the bill on the next run).
"""
from app.engine.reconcile.state import CLOSE, State
from app.engine.reconcile.types import CreditApplication, CreditNoteIn


def run(state: State, credit_notes: list[CreditNoteIn]) -> None:
    for note in credit_notes:
        if note.status not in ("received", "applied") or note.against_invoice_id not in state.invoices:
            continue
        amount = min(note.amount, state.inv_left[note.against_invoice_id])
        if amount <= CLOSE:
            continue
        state.inv_left[note.against_invoice_id] -= amount
        state.credit_applications.append(CreditApplication(note.id, note.against_invoice_id, round(amount, 2)))
        state.credit_used.add(note.id)
