"""One-tap credit note request to a supplier."""
from datetime import date

from sqlmodel import Session, select

from app.channels.base import Notifier
from app.models import CreditNote, InvoiceRow, Merchant, Supplier
from app.services.errors import Invalid, NotFound


def request_credit_note(session: Session, notifier: Notifier, merchant_id: int, invoice_id: int, amount: float,
                        today: date) -> CreditNote:
    inv = session.get(InvoiceRow, invoice_id)
    if inv is None or inv.merchant_id != merchant_id or inv.supplier_id is None:
        raise NotFound("Invoice not found")
    if amount <= 0:
        raise Invalid("Amount must be positive")
    note = session.exec(select(CreditNote).where(CreditNote.merchant_id == merchant_id,
                                                 CreditNote.against_invoice_id == invoice_id,
                                                 CreditNote.status == "expected")).first()
    if note is None:
        note = CreditNote(merchant_id=merchant_id, supplier_id=inv.supplier_id, against_invoice_id=invoice_id,
                          amount=amount, status="expected", created_on=today)
        session.add(note)
        session.flush()
    sup = session.get(Supplier, inv.supplier_id)
    if sup.linked_merchant_id:
        me = session.get(Merchant, merchant_id)
        notifier.send(sup.linked_merchant_id,
                      f"{me.name} ne bill #{inv.invoice_no} par Rs {amount:,.0f} ka credit note maanga hai.")
    return note
