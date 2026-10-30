"""Pass 4: leftover payment money is applied oldest invoice first; invoices become part-paid."""
from app.engine.reconcile.state import CLOSE, State


def run(state: State) -> None:
    for pay in state.open_payments():
        supplier_id = state.pay_supplier[pay.id]
        if supplier_id is None:
            continue
        for inv in state.open_invoices(supplier_id):
            if state.pay_left[pay.id] <= CLOSE:
                break
            amount = min(state.pay_left[pay.id], state.inv_left[inv.id])
            state.apply(inv.id, pay.id, amount, "partial", 0.8)
