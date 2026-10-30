"""Pass 3: one payment equals the sum of 2-3 open invoices from the same supplier."""
from itertools import combinations

from app.engine.reconcile.state import CLOSE, State

MAX_CANDIDATES = 10
GROUP_SIZES = (2, 3)


def run(state: State) -> None:
    for pay in state.open_payments():
        supplier_id = state.pay_supplier[pay.id]
        if supplier_id is None:
            continue
        candidates = state.open_invoices(supplier_id)[:MAX_CANDIDATES]
        group = _find_group(candidates, state, state.pay_left[pay.id])
        for inv in group:
            state.apply(inv.id, pay.id, state.inv_left[inv.id], "many_to_one", 0.85)


def _find_group(candidates, state: State, target: float):
    for size in GROUP_SIZES:
        for combo in combinations(candidates, size):
            if abs(sum(state.inv_left[i.id] for i in combo) - target) <= CLOSE:
                return combo
    return ()
