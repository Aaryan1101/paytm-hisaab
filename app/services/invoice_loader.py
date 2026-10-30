"""Turns stored invoice rows back into the Invoice schema (for validation and explanations)."""
from sqlmodel import Session, select

from app.models import InvoiceLineRow, InvoiceRow, Merchant, Supplier
from app.models.schemas import Invoice, LineItem


def to_schema(session: Session, row: InvoiceRow) -> Invoice:
    sup = session.get(Supplier, row.supplier_id) if row.supplier_id else None
    me = session.get(Merchant, row.merchant_id)
    lines = session.exec(select(InvoiceLineRow).where(InvoiceLineRow.invoice_id == row.id)).all()
    return Invoice(
        supplier_name=sup.name if sup else "Unknown", supplier_gstin=sup.gstin if sup else None, buyer_gstin=me.gstin,
        invoice_no=row.invoice_no, invoice_date=row.invoice_date, due_date=row.due_date,
        line_items=[LineItem(description=l.description, hsn=l.hsn, qty=l.qty, rate=l.rate, taxable_value=l.taxable_value,
                             gst_rate=l.gst_rate, cgst=l.cgst, sgst=l.sgst, igst=l.igst) for l in lines],
        taxable_total=row.taxable_total, tax_total=row.tax_total,
        round_off=round(row.grand_total - row.taxable_total - row.tax_total, 2), grand_total=row.grand_total,
        bill_type=row.bill_type)  # type: ignore[arg-type]


def previous_invoices(session: Session, merchant_id: int, exclude_id: int | None = None) -> list[Invoice]:
    rows = session.exec(select(InvoiceRow).where(InvoiceRow.merchant_id == merchant_id, InvoiceRow.confirmed == True)).all()  # noqa: E712
    return [to_schema(session, r) for r in rows if r.id != exclude_id]
