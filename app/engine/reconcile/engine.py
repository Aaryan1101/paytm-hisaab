"""Orchestrates the reconciliation passes in spec order (8.2). Pure: data in, result out."""
from app.engine.reconcile import (pass_exact, pass_many_to_one, pass_partial, pass_reference, pass_short_payment,
                                  supplier_resolver)
from app.engine.reconcile.state import CLOSE, State
from app.engine.reconcile.types import (CreditNoteIn, FuzzySuggestion, InvoiceIn, PaymentIn, ReconcileResult,
                                        SupplierRef)


def reconcile(invoices: list[InvoiceIn], payments: list[PaymentIn], suppliers: list[SupplierRef],
              credit_notes: list[CreditNoteIn] | None = None) -> ReconcileResult:
    state = State(invoices, payments)
    _resolve_suppliers(state, suppliers)
    pass_reference.run(state)
    pass_exact.run(state)
    pass_many_to_one.run(state)
    pass_partial.run(state)
    pass_short_payment.run(state, credit_notes or [])
    return _result(state)


def _resolve_suppliers(state: State, suppliers: list[SupplierRef]) -> None:
    for pay in state.payments.values():
        supplier_id, score = supplier_resolver.resolve(pay, suppliers)
        state.pay_supplier[pay.id] = supplier_id
        if score is not None and supplier_id is not None:
            state.fuzzy_payments.add(pay.id)
            state.fuzzy_suggestions.append(FuzzySuggestion(pay.id, supplier_id, score))


def _result(state: State) -> ReconcileResult:
    status = {}
    for inv in state.invoices.values():
        left = state.inv_left[inv.id]
        status[inv.id] = "paid" if left <= CLOSE else "part_paid" if left < inv.total - CLOSE else "open"
    return ReconcileResult(
        matches=state.matches, credit_applications=state.credit_applications, alerts=state.alerts,
        fuzzy_suggestions=state.fuzzy_suggestions, invoice_status=status,
        unmatched_payment_ids=[p.id for p in state.open_payments()],
        unpaid_invoice_ids=[i for i, s in status.items() if s != "paid"],
    )
