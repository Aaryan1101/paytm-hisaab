from fastapi import APIRouter, Depends
from sqlmodel import Session

from app import clock
from app.api.deps import get_container, get_distributor
from app.api.schemas.distributors import (IssuedInvoiceOut, IssueInvoiceIn, ReceivableOut, ReminderOut, RemindersIn,
                                          RemindersOut, SettlementOut)
from app.container import Container
from app.db import get_session
from app.models import Merchant
from app.services import distributor_service

router = APIRouter(prefix="/distributors/{distributor_id}", tags=["distributors"])


def _row(r) -> ReceivableOut:
    return ReceivableOut(retailer_id=r.retailer_id, name=r.name, outstanding=r.outstanding, overdue_amount=r.overdue_amount,
                         days_overdue=r.days_overdue, reliability=r.reliability, suggested_limit=r.suggested_limit,
                         reason_en=r.reason_en, reason_hi=r.reason_hi)


@router.get("/receivables", response_model=list[ReceivableOut])
def receivables(d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    return [_row(r) for r in distributor_service.receivables(session, d.id, clock.today())]


@router.get("/retailers/{retailer_id}", response_model=ReceivableOut)
def retailer(retailer_id: int, d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    return _row(distributor_service.retailer_row(session, d.id, retailer_id, clock.today()))


@router.get("/settlements", response_model=list[SettlementOut])
def settlements(d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    return [SettlementOut(collection_id=s.collection_id, received_at=s.received_at, payer_name=s.payer_name, gross=s.gross,
                          mdr=s.mdr, net=s.net, matched=[{"invoice_no": n, "amount": a} for n, a in s.matched],
                          status="matched" if s.matched else "unmatched")
            for s in distributor_service.settlements(session, d.id)]


@router.post("/invoices", response_model=IssuedInvoiceOut)
def issue_invoice(body: IssueInvoiceIn, d: Merchant = Depends(get_distributor), session: Session = Depends(get_session),
                  container: Container = Depends(get_container)):
    inv = distributor_service.issue_invoice(session, container.notifier(session), d.id, body.retailer_id,
                                            [l.model_dump() for l in body.lines], clock.today(), body.credit_days)
    session.commit()
    return IssuedInvoiceOut(invoice_id=inv.id, invoice_no=inv.invoice_no, grand_total=inv.grand_total, due_date=inv.due_date)


@router.post("/reminders", response_model=RemindersOut)
def reminders(body: RemindersIn, d: Merchant = Depends(get_distributor), session: Session = Depends(get_session),
              container: Container = Depends(get_container)):
    drafts = distributor_service.draft_reminders(session, d.id, clock.today(), container.reminders, body.retailer_ids, body.language)
    if body.send:
        distributor_service.send_reminders(container.notifier(session), drafts)
        session.commit()
    return RemindersOut(sent=body.send, reminders=[ReminderOut(retailer_id=x.retailer_id, retailer_name=x.retailer_name, amount=x.amount,
                                                              days_overdue=x.days_overdue, tone=x.tone, text=x.text) for x in drafts])
