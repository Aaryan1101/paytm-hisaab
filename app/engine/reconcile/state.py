"""Mutable working state shared by the reconciliation passes."""
from app.engine.reconcile.types import (AlertOut, CreditApplication, FuzzySuggestion, InvoiceIn, MatchOut,
                                        PaymentIn)

CLOSE = 0.5  # rupees: amounts within this are treated as equal / fully settled
FUZZY_CONFIDENCE_CAP = 0.85  # payments matched via a guessed supplier stay below the 0.9 "confirm?" line


class State:
    def __init__(self, invoices: list[InvoiceIn], payments: list[PaymentIn]):
        self.invoices = {i.id: i for i in invoices}
        self.payments = {p.id: p for p in payments}
        self.inv_left = {i.id: i.total - i.already_applied for i in invoices}
        self.pay_left = {p.id: p.amount - p.already_applied for p in payments}
        self.pay_supplier: dict[int, int | None] = {p.id: p.supplier_id for p in payments}
        self.fuzzy_payments: set[int] = set()
        self.matches: list[MatchOut] = []
        self.credit_applications: list[CreditApplication] = []
        self.alerts: list[AlertOut] = []
        self.fuzzy_suggestions: list[FuzzySuggestion] = []

    def open_invoices(self, supplier_id: int | None = None) -> list[InvoiceIn]:
        out = [i for i in self.invoices.values()
               if self.inv_left[i.id] > CLOSE and (supplier_id is None or i.supplier_id == supplier_id)]
        return sorted(out, key=lambda i: (i.invoice_date, i.id))

    def open_payments(self) -> list[PaymentIn]:
        out = [p for p in self.payments.values() if self.pay_left[p.id] > CLOSE]
        return sorted(out, key=lambda p: (p.paid_at, p.id))

    def apply(self, invoice_id: int, payment_id: int, amount: float, method: str, confidence: float) -> None:
        if payment_id in self.fuzzy_payments:
            confidence = min(confidence, FUZZY_CONFIDENCE_CAP)
        self.inv_left[invoice_id] -= amount
        self.pay_left[payment_id] -= amount
        self.matches.append(MatchOut(invoice_id, payment_id, round(amount, 2), method, confidence))
