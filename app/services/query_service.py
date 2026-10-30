"""A retailer asks a supplier about a bill; the supplier's answer flows back."""
from sqlmodel import Session

from app.channels.base import Button, Notifier
from app.models import InvoiceRow, Merchant, Supplier, SupplierQuery
from app.services import invoice_service
from app.services.errors import Invalid, NotFound


def ask_supplier(session: Session, notifier: Notifier, merchant_id: int, invoice_id: int) -> SupplierQuery:
    inv = session.get(InvoiceRow, invoice_id)
    if inv is None or inv.merchant_id != merchant_id or inv.supplier_id is None:
        raise NotFound("Invoice not found")
    sup = session.get(Supplier, inv.supplier_id)
    me = session.get(Merchant, merchant_id)
    text = f"{me.name} ne bill #{inv.invoice_no} par sawaal poocha hai"
    query = SupplierQuery(merchant_id=merchant_id, supplier_id=sup.id, invoice_id=invoice_id, text=text)
    session.add(query)
    session.flush()
    if sup.linked_merchant_id:
        notifier.send(sup.linked_merchant_id, text,
                      [Button(f"qa:{query.id}:duplicate", "Duplicate hai"), Button(f"qa:{query.id}:new_bill", "Naya bill hai")])
    return query


def answer_query(session: Session, notifier: Notifier, query_id: int, answer: str) -> SupplierQuery:
    if answer not in ("duplicate", "new_bill"):
        raise Invalid("Answer must be duplicate or new_bill")
    q = session.get(SupplierQuery, query_id)
    if q is None:
        raise NotFound("Query not found")
    if q.status == "answered":
        raise Invalid("Query already answered")
    q.status, q.answer = "answered", answer
    session.add(q)
    if answer == "duplicate":
        invoice_service.discard_invoice(session, q.merchant_id, q.invoice_id)
        notifier.send(q.merchant_id, "Supplier ne bataya: yeh bill duplicate hai. Maine ledger se hata diya.")
    else:
        invoice_service.confirm_invoice(session, q.merchant_id, q.invoice_id)
        notifier.send(q.merchant_id, "Supplier ne bataya: yeh naya bill hai. Ledger mein jod diya.")
    session.flush()
    return q
