"""Pass 2: same supplier, payment equals one open invoice, paid within -10..+45 days of its date."""
from app.engine.reconcile.state import CLOSE, State

MIN_DAYS, MAX_DAYS = -10, 45


def run(state: State) -> None:
    for pay in state.open_payments():
        supplier_id = state.pay_supplier[pay.id]
        if supplier_id is None:
            continue
        for inv in state.open_invoices(supplier_id):
            days = (pay.paid_at - inv.invoice_date).days
            if abs(state.inv_left[inv.id] - state.pay_left[pay.id]) <= CLOSE and MIN_DAYS <= days <= MAX_DAYS:
                state.apply(inv.id, pay.id, state.pay_left[pay.id], "exact", 0.95)
                break
