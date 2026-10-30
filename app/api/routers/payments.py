from fastapi import APIRouter, Depends
from sqlmodel import Session

from app import clock
from app.api.deps import merchant_or_404
from app.api.schemas.merchants import AlertOut
from app.api.schemas.payments import (CashIn, ConfirmPayeeIn, ConfirmPaymentIn, DraftIn, DraftOut,
                                      PaymentRecordOut)
from app.db import get_session
from app.models import PaymentDraft, PaymentOut
from app.services import payment_service, reconcile_service

router = APIRouter(tags=["payments"])


def _draft(d: PaymentDraft) -> DraftOut:
    return DraftOut(id=d.id, supplier_id=d.supplier_id, amount=d.amount, source=d.source, status=d.status, upi_link=d.upi_link)


def _payment(p: PaymentOut) -> PaymentRecordOut:
    return PaymentRecordOut(id=p.id, amount=p.amount, mode=p.mode, paid_at=p.paid_at, confirmed=p.confirmed, supplier_id=p.supplier_id)


@router.post("/payments/draft", response_model=DraftOut)
def draft(body: DraftIn, session: Session = Depends(get_session)):
    merchant_or_404(session, body.merchant_id)
    d = payment_service.draft_payment(session, body.merchant_id, body.supplier_id, body.amount, body.source)
    session.commit()
    return _draft(d)


@router.post("/payments/{draft_id}/confirm", response_model=PaymentRecordOut)
def confirm(draft_id: int, body: ConfirmPaymentIn, session: Session = Depends(get_session)):
    p = payment_service.confirm_payment(session, body.merchant_id, draft_id, clock.now())
    session.commit()
    return _payment(p)


@router.post("/payments/cash", response_model=PaymentRecordOut)
def log_cash(body: CashIn, session: Session = Depends(get_session)):
    merchant_or_404(session, body.merchant_id)
    p = payment_service.log_cash_payment(session, body.merchant_id, body.supplier_id, body.amount, clock.now())
    session.commit()
    return _payment(p)


@router.post("/payments/cash/{payment_id}/confirm", response_model=PaymentRecordOut)
def confirm_cash(payment_id: int, body: ConfirmPaymentIn, session: Session = Depends(get_session)):
    p = payment_service.confirm_cash_payment(session, body.merchant_id, payment_id)
    session.commit()
    return _payment(p)


@router.delete("/payments/cash/{payment_id}", status_code=204)
def cancel_cash(payment_id: int, merchant_id: int, session: Session = Depends(get_session)):
    payment_service.cancel_cash_payment(session, merchant_id, payment_id)
    session.commit()


@router.post("/merchants/{merchant_id}/payments/{payment_id}/confirm-payee")
def confirm_payee(merchant_id: int, payment_id: int, body: ConfirmPayeeIn, session: Session = Depends(get_session)):
    merchant_or_404(session, merchant_id)
    pay = session.get(PaymentOut, payment_id)
    if pay is None or pay.merchant_id != merchant_id:
        from app.services.errors import NotFound
        raise NotFound("Payment not found")
    reconcile_service.confirm_payee(session, payment_id, body.supplier_id)
    session.commit()
    return {"ok": True}
