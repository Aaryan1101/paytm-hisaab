"""Two-step payments (draft, then confirm) and cash entries that need confirmation. The AI never calls confirm."""
from datetime import datetime
from urllib.parse import quote

from sqlmodel import Session, select

from app.models import Merchant, PaymentDraft, PaymentOut, Supplier
from app.services import credit_service, payment_recorder, reconcile_service, settlement_service
from app.services.errors import Invalid, NotFound


def _supplier(session: Session, merchant_id: int, supplier_id: int) -> Supplier:
    sup = session.get(Supplier, supplier_id)
    if sup is None or sup.merchant_id != merchant_id:
        raise NotFound("Supplier not found")
    return sup


def credit_used(session: Session, merchant_id: int) -> float:
    return sum(p.amount for p in session.exec(select(PaymentOut).where(PaymentOut.merchant_id == merchant_id,
                                                                       PaymentOut.mode == "credit_line")).all())


def draft_payment(session: Session, merchant_id: int, supplier_id: int, amount: float, source: str) -> PaymentDraft:
    sup = _supplier(session, merchant_id, supplier_id)
    if amount <= 0:
        raise Invalid("Amount must be positive")
    if source not in ("bank", "credit"):
        raise Invalid("Source must be bank or credit")
    if source == "credit":
        offer = credit_service.accepted_offer(session, merchant_id)
        if offer is None:
            raise Invalid("Accept a credit offer first")
        if credit_used(session, merchant_id) + amount > offer.limit_amount:
            raise Invalid("Amount exceeds your remaining credit limit")
    link = f"upi://pay?pa={quote(sup.payee_vpa or '')}&pn={quote(sup.name)}&am={amount:.2f}&cu=INR"
    draft = PaymentDraft(merchant_id=merchant_id, supplier_id=supplier_id, amount=amount, source=source, upi_link=link)
    session.add(draft)
    session.flush()
    return draft


def confirm_payment(session: Session, merchant_id: int, draft_id: int, now: datetime) -> PaymentOut:
    draft = session.get(PaymentDraft, draft_id)
    if draft is None or draft.merchant_id != merchant_id:
        raise NotFound("Draft not found")
    if draft.status != "drafted":
        raise Invalid(f"Draft is already {draft.status}")
    sup = _supplier(session, merchant_id, draft.supplier_id)
    pay = payment_recorder.record_upi_payment(session, merchant_id, sup, draft.amount, now,
                                              mode="credit_line" if draft.source == "credit" else "upi")
    pay.supplier_id = sup.id
    if draft.source == "bank":
        merchant = session.get(Merchant, merchant_id)
        merchant.opening_balance = round(merchant.opening_balance - draft.amount, 2)
        session.add(merchant)
    draft.status = "confirmed"
    session.add_all([pay, draft])
    session.flush()
    reconcile_service.reconcile_merchant(session, merchant_id)
    if sup.linked_merchant_id:
        settlement_service.reconcile_distributor(session, sup.linked_merchant_id)
    return pay


def log_cash_payment(session: Session, merchant_id: int, supplier_id: int, amount: float, paid_at: datetime) -> PaymentOut:
    """Voice/WhatsApp cash entry: stored unconfirmed, ignored by reconciliation until the merchant confirms."""
    sup = _supplier(session, merchant_id, supplier_id)
    if amount <= 0:
        raise Invalid("Amount must be positive")
    return payment_recorder.record_cash_payment(session, merchant_id, sup, amount, paid_at, confirmed=False)


def confirm_cash_payment(session: Session, merchant_id: int, payment_id: int) -> PaymentOut:
    pay = session.get(PaymentOut, payment_id)
    if pay is None or pay.merchant_id != merchant_id or pay.mode != "cash":
        raise NotFound("Cash entry not found")
    pay.confirmed = True
    session.add(pay)
    session.flush()
    reconcile_service.reconcile_merchant(session, merchant_id)
    return pay


def cancel_cash_payment(session: Session, merchant_id: int, payment_id: int) -> None:
    pay = session.get(PaymentOut, payment_id)
    if pay is None or pay.merchant_id != merchant_id or pay.confirmed:
        raise NotFound("Pending cash entry not found")
    session.delete(pay)
    session.flush()


def cancel_draft(session: Session, merchant_id: int, draft_id: int) -> PaymentDraft:
    draft = session.get(PaymentDraft, draft_id)
    if draft is None or draft.merchant_id != merchant_id:
        raise NotFound("Draft not found")
    if draft.status != "drafted":
        raise Invalid(f"Draft is already {draft.status}")
    draft.status = "cancelled"
    session.add(draft)
    session.flush()
    return draft
