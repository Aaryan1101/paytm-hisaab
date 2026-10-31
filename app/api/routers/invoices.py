from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlmodel import Session

from app.api.deps import get_container, merchant_or_404
from app.api.schemas.invoices import (AnswerIn, ConfirmIn, CreditNoteOut, CreditNoteRequestIn, DuplicateOut, IngestOut, InvoiceStateOut, IssueOut,
                                      QueryOut)
from app.container import Container
from app.db import get_session
from app.models import InvoiceRow, SupplierQuery
from app import clock
from app.services import credit_note_service, ingest_service, invoice_service, query_service
from app.services.errors import Invalid

router = APIRouter(tags=["invoices"])
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _state(inv: InvoiceRow) -> InvoiceStateOut:
    return InvoiceStateOut(id=inv.id, invoice_no=inv.invoice_no, status=inv.status, confirmed=inv.confirmed,
                           grand_total=inv.grand_total, amount_settled=inv.amount_settled)


def _query(q: SupplierQuery) -> QueryOut:
    return QueryOut(id=q.id, status=q.status, invoice_id=q.invoice_id, answer=q.answer)


@router.post("/invoices/ingest", response_model=IngestOut)
def ingest(merchant_id: int = Form(...), source: str = Form("app"), file: UploadFile = File(...),
           session: Session = Depends(get_session), container: Container = Depends(get_container)):
    merchant_or_404(session, merchant_id)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise Invalid("File is larger than 15 MB")
    r = ingest_service.ingest_invoice(session, merchant_id, data, source, container.extractor, container.media)
    session.commit()
    return IngestOut(
        invoice_id=r.invoice_id, invoice=r.invoice, field_confidence=r.field_confidence,
        low_confidence_fields=r.low_confidence_fields, image_url=r.image_url,
        issues=[IssueOut(code=i.code, severity=i.severity, message_en=i.message_en, message_hi=i.message_hi,
                         field=i.field, line_index=i.line_index) for i in r.issues],
        duplicate=DuplicateOut(invoice_id=r.duplicate.invoice_id, invoice_no=r.duplicate.invoice_no,
                               invoice_date=r.duplicate.invoice_date, paid_on=r.duplicate.paid_on, amount=r.duplicate.amount) if r.duplicate else None,
        supplier_name=r.supplier_name)


@router.post("/invoices/{invoice_id}/confirm", response_model=InvoiceStateOut)
def confirm(invoice_id: int, merchant_id: int, body: ConfirmIn | None = None, session: Session = Depends(get_session)):
    inv = invoice_service.confirm_invoice(session, merchant_id, invoice_id, body.corrections if body else None)
    session.commit()
    return _state(inv)


@router.post("/invoices/{invoice_id}/discard", response_model=InvoiceStateOut)
def discard(invoice_id: int, merchant_id: int, session: Session = Depends(get_session)):
    inv = invoice_service.discard_invoice(session, merchant_id, invoice_id)
    session.commit()
    return _state(inv)


@router.post("/invoices/{invoice_id}/ask-supplier", response_model=QueryOut)
def ask_supplier(invoice_id: int, merchant_id: int, session: Session = Depends(get_session),
                 container: Container = Depends(get_container)):
    q = query_service.ask_supplier(session, container.notifier(session), merchant_id, invoice_id)
    session.commit()
    return _query(q)


@router.post("/queries/{query_id}/answer", response_model=QueryOut)
def answer(query_id: int, body: AnswerIn, session: Session = Depends(get_session),
           container: Container = Depends(get_container)):
    q = query_service.answer_query(session, container.notifier(session), query_id, body.answer)
    session.commit()
    return _query(q)


@router.post("/invoices/{invoice_id}/request-credit-note", response_model=CreditNoteOut)
def request_credit_note(invoice_id: int, merchant_id: int, body: CreditNoteRequestIn, session: Session = Depends(get_session),
                        container: Container = Depends(get_container)):
    """One-tap "ask the supplier for a credit note". Asking twice for the same bill returns the same request."""
    note = credit_note_service.request_credit_note(session, container.notifier(session), merchant_id, invoice_id, body.amount, clock.today())
    session.commit()
    return CreditNoteOut(id=note.id, invoice_id=note.against_invoice_id, amount=note.amount, status=note.status)
