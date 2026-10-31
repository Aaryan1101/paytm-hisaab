from fastapi import APIRouter, Depends
from sqlmodel import Session

from app import clock
from app.api.deps import get_container, get_distributor
from app.api.schemas.distributors import (CreditNoteIssuedOut, CreditNoteIssueIn, IssuedInvoiceOut, IssueInvoiceIn,
                                          MatchedInvoiceOut, OpenQueryOut, ReceivableOut, ReminderOut, RemindersIn,
                                          RemindersOut, RetailerDetailOut, RetailerInvoiceOut, SettlementOut)
from app.api.schemas.merchants import PendingMatchOut
from app.container import Container
from app.db import get_session
from app.models import Merchant
from app.services import credit_note_service, distributor_service, match_service

router = APIRouter(prefix="/distributors/{distributor_id}", tags=["distributors"])


def _row(r) -> ReceivableOut:
    return ReceivableOut(retailer_id=r.retailer_id, name=r.name, outstanding=r.outstanding, overdue_amount=r.overdue_amount,
                         days_overdue=r.days_overdue, reliability=r.reliability, suggested_limit=r.suggested_limit,
                         reason_en=r.reason_en, reason_hi=r.reason_hi)


@router.get("/receivables", response_model=list[ReceivableOut])
def receivables(d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    return [_row(r) for r in distributor_service.receivables(session, d.id, clock.today())]


def _settlement(s) -> SettlementOut:
    return SettlementOut(collection_id=s.collection_id, received_at=s.received_at, payer_id=s.payer_id, payer_name=s.payer_name,
                         gross=s.gross, mdr=s.mdr, net=s.net, status="matched" if s.matched else "unmatched",
                         matched=[MatchedInvoiceOut(invoice_no=m.invoice_no, amount=m.amount, match_id=m.match_id,
                                                    confidence=m.confidence, confirmed=m.confirmed) for m in s.matched])


def _query(q) -> OpenQueryOut:
    return OpenQueryOut(query_id=q.query_id, retailer_id=q.retailer_id, retailer_name=q.retailer_name, invoice_id=q.invoice_id,
                        invoice_no=q.invoice_no, text=q.text, created_at=q.created_at)


@router.get("/retailers/{retailer_id}", response_model=RetailerDetailOut)
def retailer(retailer_id: int, d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    """Summary plus that retailer's bills, receipts and unanswered questions."""
    det = distributor_service.retailer_detail(session, d.id, retailer_id, clock.today())
    return RetailerDetailOut(**_row(det.summary).model_dump(),
                             invoices=[RetailerInvoiceOut(**vars(i)) for i in det.invoices],
                             receipts=[_settlement(r) for r in det.receipts], open_queries=[_query(q) for q in det.open_queries])


@router.get("/settlements", response_model=list[SettlementOut])
def settlements(d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    return [_settlement(s) for s in distributor_service.settlements(session, d.id)]


@router.get("/queries", response_model=list[OpenQueryOut])
def queries(d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    """Open retailer questions across all retailers. Answer one with POST /queries/{id}/answer."""
    return [_query(q) for q in distributor_service.open_queries(session, d.id)]


@router.get("/matches/pending", response_model=list[PendingMatchOut])
def pending_matches(d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    """Receipt-to-bill matches the engine was unsure about, for the "Confirm a suggested match" action."""
    return [PendingMatchOut(match_id=p.match_id, invoice_id=p.invoice_id, invoice_no=p.invoice_no, counterparty=p.counterparty,
                            amount=p.amount, method=p.method, confidence=p.confidence, when=p.when)
            for p in match_service.pending_for_distributor(session, d.id)]


@router.post("/matches/{match_id}/confirm")
def confirm_match(match_id: int, d: Merchant = Depends(get_distributor), session: Session = Depends(get_session)):
    match_service.confirm_for_distributor(session, d.id, match_id)
    session.commit()
    return {"ok": True}


@router.post("/credit-notes", response_model=CreditNoteIssuedOut)
def issue_credit_note(body: CreditNoteIssueIn, d: Merchant = Depends(get_distributor), session: Session = Depends(get_session),
                      container: Container = Depends(get_container)):
    """Credit a retailer's bill. The retailer's ledger updates and they are notified."""
    note = credit_note_service.issue_credit_note(session, container.notifier(session), d.id, body.retailer_id, body.invoice_id,
                                                 body.amount, clock.today())
    session.commit()
    return CreditNoteIssuedOut(credit_note_id=note.id, invoice_id=note.against_invoice_id, amount=note.amount, status=note.status)


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
    drafts = distributor_service.apply_edits(drafts, body.texts)
    if body.send:
        distributor_service.send_reminders(container.notifier(session), drafts)
        session.commit()
    return RemindersOut(sent=body.send, reminders=[ReminderOut(retailer_id=x.retailer_id, retailer_name=x.retailer_name, amount=x.amount,
                                                              days_overdue=x.days_overdue, tone=x.tone, text=x.text) for x in drafts])
