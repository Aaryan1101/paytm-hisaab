"""Pass 1: the payment remark names the invoice number."""
from app.engine.reconcile.state import CLOSE, State


def run(state: State) -> None:
    for pay in state.open_payments():
        if not pay.remark:
            continue
        remark = pay.remark.casefold()
        for inv in state.open_invoices():
            if state.pay_left[pay.id] <= CLOSE:
                break
            if inv.invoice_no.casefold() in remark:
                state.apply(inv.id, pay.id, min(state.pay_left[pay.id], state.inv_left[inv.id]), "reference", 1.0)
