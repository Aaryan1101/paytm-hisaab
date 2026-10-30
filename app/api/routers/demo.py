from fastapi import APIRouter, Depends
from sqlmodel import Session

from app import clock
from app.api.deps import merchant_or_404
from app.api.schemas.demo import SimulateCustomerPaymentIn, SimulatePaymentIn, SimulatePaymentOut
from app.db import get_session
from app.services import demo_service

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/reset")
def reset(session: Session = Depends(get_session)):
    demo_service.reset(session)
    session.commit()
    return {"ok": True}


@router.post("/simulate-payment", response_model=SimulatePaymentOut)
def simulate_payment(body: SimulatePaymentIn, session: Session = Depends(get_session)):
    merchant_or_404(session, body.payer_id)
    r = demo_service.simulate_payment(session, body.payer_id, body.supplier_name, body.amount, clock.now())
    session.commit()
    return SimulatePaymentOut(gross=r.gross, mdr=r.mdr, net=r.net, matched=[{"invoice_no": n, "amount": a} for n, a in r.matched],
                              reliability_before=r.retailer_reliability_before, reliability_after=r.retailer_reliability_after)


@router.post("/simulate-customer-payment")
def simulate_customer_payment(body: SimulateCustomerPaymentIn, session: Session = Depends(get_session)):
    merchant_or_404(session, body.merchant_id)
    col = demo_service.simulate_customer_payment(session, body.merchant_id, body.amount, clock.now())
    session.commit()
    return {"collection_id": col.id, "amount": col.amount}
