from datetime import date

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app import clock
from app.api.deps import get_container, merchant_or_404
from app.api.schemas.demo import JobRunOut, SimulateCustomerPaymentIn, SimulatePaymentIn, SimulatePaymentOut
from app.db import get_session
from app.container import Container
from app.jobs import notifications
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


@router.post("/run-due-reminders", response_model=JobRunOut)
def run_due_reminders(on: date | None = None, session: Session = Depends(get_session), container: Container = Depends(get_container)):
    """Send "bill due tomorrow" messages (and Soundbox announcements) now. `on` pretends today is that date, e.g. 2026-11-03."""
    sent = notifications.send_due_tomorrow(session, container.notifier(session), on or clock.today())
    session.commit()
    return JobRunOut(sent=[{"merchant_id": x.merchant_id, "kind": x.kind, "text": x.text} for x in sent])


@router.post("/run-weekly-digest", response_model=JobRunOut)
def run_weekly_digest(on: date | None = None, session: Session = Depends(get_session), container: Container = Depends(get_container)):
    """Send the weekly payables digest now (once per ISO week per merchant)."""
    sent = notifications.send_weekly_digest(session, container.notifier(session), on or clock.today())
    session.commit()
    return JobRunOut(sent=[{"merchant_id": x.merchant_id, "kind": x.kind, "text": x.text} for x in sent])
