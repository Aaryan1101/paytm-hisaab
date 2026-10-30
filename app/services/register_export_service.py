"""Purchase register CSV for the CA."""
import csv
import io

from sqlmodel import Session, select

from app.models import InvoiceLineRow, InvoiceRow, Supplier

HEADER = ["Date", "Invoice No", "Supplier", "GSTIN", "Taxable", "CGST", "SGST", "IGST", "Total", "Status"]


def purchase_register_csv(session: Session, merchant_id: int, month: str) -> tuple[str, str]:
    """Return (filename, csv_text) for confirmed bills dated in YYYY-MM."""
    suppliers = {s.id: s for s in session.exec(select(Supplier).where(Supplier.merchant_id == merchant_id)).all()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    invoices = [i for i in session.exec(select(InvoiceRow).where(
        InvoiceRow.merchant_id == merchant_id, InvoiceRow.confirmed == True)  # noqa: E712
        .order_by(InvoiceRow.invoice_date, InvoiceRow.id)).all() if i.invoice_date.strftime("%Y-%m") == month]
    for inv in invoices:
        lines = session.exec(select(InvoiceLineRow).where(InvoiceLineRow.invoice_id == inv.id)).all()
        sup = suppliers.get(inv.supplier_id)
        w.writerow([inv.invoice_date.isoformat(), inv.invoice_no, sup.name if sup else "", sup.gstin if sup and sup.gstin else "",
                    f"{inv.taxable_total:.2f}", f"{sum(l.cgst for l in lines):.2f}", f"{sum(l.sgst for l in lines):.2f}",
                    f"{sum(l.igst for l in lines):.2f}", f"{inv.grand_total:.2f}", inv.status])
    return f"purchase_register_{merchant_id}_{month}.csv", buf.getvalue()
