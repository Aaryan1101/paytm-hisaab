"""Builds invoices whose line, tax and total maths are internally consistent."""
import random
from datetime import date, timedelta

from sqlmodel import Session

from app.models import InvoiceLineRow, InvoiceRow, Supplier

Item = tuple[str, str, float, str, float]


def split_lines(rng: random.Random, pool: list[Item], grand_total: float, intra: bool) -> tuple[list[dict], float, float, float]:
    """Return (lines, taxable_total, tax_total, round_off) summing exactly to grand_total."""
    k = min(len(pool), rng.randint(3, 5))
    items = rng.sample(pool, k)
    weights = [rng.random() + 0.4 for _ in items]
    scale = sum(weights)
    lines: list[dict] = []
    gross_so_far = 0.0
    for idx, (desc, hsn, rate_pct, unit, base) in enumerate(items):
        if idx < k - 1:
            taxable = round(weights[idx] / scale * grand_total / (1 + rate_pct / 100), 2)
        else:
            taxable = round((grand_total - gross_so_far) / (1 + rate_pct / 100), 2)
        tax = round(taxable * rate_pct / 100, 2)
        gross_so_far += taxable + tax
        qty = max(1, round(taxable / (base * rng.uniform(0.95, 1.05))))
        half = round(tax / 2, 2)
        lines.append(dict(description=desc, hsn=hsn, qty=float(qty), rate=round(taxable / qty, 4), taxable_value=taxable,
                          gst_rate=rate_pct, unit=unit, cgst=half if intra else 0.0, sgst=half if intra else 0.0,
                          igst=0.0 if intra else tax, _tax=tax))
    taxable_total = round(sum(l["taxable_value"] for l in lines), 2)
    tax_total = round(sum(l["_tax"] for l in lines), 2)
    return lines, taxable_total, tax_total, round(grand_total - taxable_total - tax_total, 2)


def create_invoice(session: Session, rng: random.Random, merchant_id: int, supplier: Supplier, pool: list[Item],
                   invoice_no: str, invoice_date: date, grand_total: float, intra: bool = True,
                   credit_days: int = 14, source: str = "app", confirmed: bool = True) -> InvoiceRow:
    lines, taxable_total, tax_total, _ = split_lines(rng, pool, grand_total, intra)
    inv = InvoiceRow(merchant_id=merchant_id, supplier_id=supplier.id, invoice_no=invoice_no, invoice_date=invoice_date,
                     due_date=invoice_date + timedelta(days=credit_days), taxable_total=taxable_total,
                     tax_total=tax_total, grand_total=grand_total, bill_type="gst_invoice", source=source,
                     confirmed=confirmed)
    session.add(inv)
    session.flush()
    for l in lines:
        session.add(InvoiceLineRow(invoice_id=inv.id, **{k: v for k, v in l.items() if not k.startswith("_")}))
    return inv
