"""Neha's October IMS list: mirrors her bills, plus planted anomalies."""
import random
from datetime import date

from sqlmodel import Session, select

from app.models import CreditNote, ImsEntry, InvoiceRow, Supplier
from app.seed.context import SeedContext

MONTH = "2026-10"


def _entry(inv: InvoiceRow, sup: Supplier, **kw) -> ImsEntry:
    base = dict(merchant_id=inv.merchant_id, month=MONTH, supplier_gstin=sup.gstin, supplier_name=sup.name,
                invoice_no=inv.invoice_no, invoice_date=inv.invoice_date, taxable=inv.taxable_total,
                tax=inv.tax_total, invoice_id=inv.id)
    return ImsEntry(**{**base, **kw})


def seed_ims(session: Session, rng: random.Random, ctx: SeedContext) -> None:
    invoices = session.exec(select(InvoiceRow).where(
        InvoiceRow.merchant_id == ctx.neha.id, InvoiceRow.invoice_date >= date(2026, 10, 1),
        InvoiceRow.invoice_date <= date(2026, 10, 31)).order_by(InvoiceRow.invoice_date, InvoiceRow.id)).all()
    sups = {s.id: s for s in session.exec(select(Supplier).where(Supplier.merchant_id == ctx.neha.id)).all()}
    entries = [_entry(i, sups[i.supplier_id]) for i in invoices]
    if len(entries) >= 5:
        session.add(_entry(invoices[0], sups[invoices[0].supplier_id]))          # duplicate entry -> reject
        entries[1].taxable += 500                                                 # amount differs -> pending
        cn_sup = sups[invoices[2].supplier_id]
        session.add(CreditNote(merchant_id=ctx.neha.id, supplier_id=cn_sup.id, amount=1_500.0, status="expected"))
        entries.pop()                                                             # bill missing from IMS -> alert
    bhatia, seth = ctx.neha_suppliers["Bhatia Biscuits"], ctx.neha_suppliers["Seth Detergents"]
    entries.append(ImsEntry(merchant_id=ctx.neha.id, month=MONTH, supplier_gstin=seth.gstin, supplier_name=seth.name,
                            invoice_no="SD-9001", invoice_date=date(2026, 10, 9), taxable=8_000.0, tax=400.0,
                            not_purchased=True))                                  # not purchased -> reject
    entries.append(ImsEntry(merchant_id=ctx.neha.id, month=MONTH, supplier_gstin=bhatia.gstin, supplier_name=bhatia.name,
                            invoice_no="BB-7777", invoice_date=date(2026, 10, 11), taxable=5_000.0, tax=250.0))
    session.add_all(entries)
    session.flush()
