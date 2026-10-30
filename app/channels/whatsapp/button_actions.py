"""Handles taps on interactive buttons. Button ids look like 'kind:id:action'."""
from sqlmodel import Session

from app import clock
from app.channels.base import Notifier
from app.services import invoice_service, payment_service, query_service
from app.services.errors import Invalid, ServiceError


def perform(session: Session, notifier: Notifier, merchant_id: int, kind: str, ref_id: int, action: str) -> str:
    """Run one business action; raises KeyError for an unknown (kind, action) and ServiceError for a failed one."""
    return _ACTIONS[(kind, action)](session, notifier, merchant_id, ref_id)


def handle(session: Session, notifier: Notifier, merchant_id: int, button_id: str) -> str:
    """Legacy stateless buttons ('kind:id:action'). Returns the reply text for the person who tapped."""
    try:
        kind, ref, action = button_id.split(":")
        ref_id = int(ref)
    except ValueError:
        return "Yeh button samajh nahi aaya."
    try:
        return perform(session, notifier, merchant_id, kind, ref_id, action)
    except KeyError:
        return "Yeh button samajh nahi aaya."
    except ServiceError as e:
        return f"Nahi ho paya: {e.message}"


def _bill_ok(s, n, m, ref):
    invoice_service.confirm_invoice(s, m, ref)
    return "Bill ledger mein jod diya ✅"


def _bill_no(s, n, m, ref):
    invoice_service.discard_invoice(s, m, ref)
    return "Bill hata diya."


def _dup_ask(s, n, m, ref):
    q = query_service.ask_supplier(s, n, m, ref)
    return "Supplier ko message bhej diya. Jawab aate hi bataunga." if q else ""


def _cash_ok(s, n, m, ref):
    p = payment_service.confirm_cash_payment(s, m, ref)
    return f"₹{p.amount:,.0f} cash payment pakka kar diya ✅"


def _cash_no(s, n, m, ref):
    payment_service.cancel_cash_payment(s, m, ref)
    return "Cash entry hata di."


def _pay_ok(s, n, m, ref):
    p = payment_service.confirm_payment(s, m, ref, clock.now())
    return f"₹{p.amount:,.0f} ka payment ho gaya ✅"


def _pay_no(s, n, m, ref):
    payment_service.cancel_draft(s, m, ref)
    return "Payment cancel kar diya."


def _answer(answer: str):
    def run(s, n, m, ref):
        query_service.answer_query(s, n, ref, answer)
        return "Jawab bhej diya. Dhanyavaad."
    return run


_ACTIONS = {("bill", "ok"): _bill_ok, ("bill", "no"): _bill_no, ("dup", "ignore"): _bill_no, ("dup", "new"): _bill_ok,
            ("dup", "ask"): _dup_ask, ("cash", "ok"): _cash_ok, ("cash", "no"): _cash_no, ("pay", "ok"): _pay_ok,
            ("pay", "no"): _pay_no, ("qa", "duplicate"): _answer("duplicate"), ("qa", "new_bill"): _answer("new_bill")}
