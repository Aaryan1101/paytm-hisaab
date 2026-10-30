"""Planted demo scenarios for Ramesh (S1, S2, S6, S7, this week's dues) and Neha's cancelled supplier (S4)."""
import random
from datetime import date

from sqlmodel import Session

from app.models import CreditNote
from app.seed import catalog
from app.seed.context import SeedContext
from app.seed.invoice_builder import create_invoice
from app.seed.payments import record_upi_payment

_CATEGORY = {name: cat for name, cat, _a, _l in catalog.RAMESH_SUPPLIERS}


def _inv(session, rng, ctx, supplier_name, no, d, total, credit_days=14):
    sup = ctx.ramesh_suppliers[supplier_name]
    return create_invoice(session, rng, ctx.ramesh.id, sup, catalog.ITEMS[_CATEGORY[supplier_name]], no, d, total,
                          credit_days=credit_days, source="whatsapp")


def plant_ramesh(session: Session, rng: random.Random, ctx: SeedContext) -> None:
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    # S1: ST-2291 already paid on 12 Oct; the demo re-sends this bill as a photo
    _inv(session, rng, ctx, "Sharma Traders", "ST-2291", date(2026, 10, 12), 18_640.0)
    record_upi_payment(session, rng, ctx.ramesh.id, sharma, 18_640.0, date(2026, 10, 12))
    # S2: paid 40,000 on a 42,300 bill; the 2,300 credit note was promised but never issued
    inv = _inv(session, rng, ctx, "Sharma Traders", "ST-2250", date(2026, 10, 3), 42_300.0)
    record_upi_payment(session, rng, ctx.ramesh.id, sharma, 40_000.0, date(2026, 10, 9))
    session.add(CreditNote(merchant_id=ctx.ramesh.id, supplier_id=sharma.id, against_invoice_id=inv.id, amount=2_300.0,
                           status="expected", created_on=date(2026, 10, 9)))
    # S7: unknown payee name on the UPI statement, no VPA to go by
    _inv(session, rng, ctx, "Sharma Traders", "ST-2260", date(2026, 10, 10), 8_000.0)
    record_upi_payment(session, rng, ctx.ramesh.id, sharma, 8_000.0, date(2026, 10, 20),
                       payee_name="SHARMA TRDRS LKO", use_vpa=False)
    session.flush()


def plant_dues(session: Session, rng: random.Random, ctx: SeedContext) -> None:
    """This week's dues total Rs 1,12,400 over 5 suppliers; Diwali restock bills fall due after."""
    due_this_week = [("Sharma Traders", "ST-2302", date(2026, 10, 21), 42_300.0),
                     ("Agarwal Dairy", "AD-0718", date(2026, 10, 22), 28_000.0),
                     ("Gupta Oil Mills", "GO-5531", date(2026, 10, 20), 19_800.0),
                     ("Singh Rice Co", "SR-1180", date(2026, 10, 22), 14_200.0),
                     ("Mishra Biscuits", "MB-902", date(2026, 10, 23), 8_100.0)]
    later = [("Sharma Traders", "ST-2308", date(2026, 10, 28), 18_640.0),   # S6: with ST-2309 one payment clears both
             ("Sharma Traders", "ST-2309", date(2026, 10, 29), 12_860.0),
             ("Verma Snacks", "VS-441", date(2026, 10, 27), 22_000.0),
             ("Kapoor Beverages", "KB-77", date(2026, 10, 29), 31_000.0)]
    for name, no, d, total in due_this_week:
        _inv(session, rng, ctx, name, no, d, total)
    for name, no, d, total in later:  # 21-day terms: due after the 14-day forecast window
        _inv(session, rng, ctx, name, no, d, total, credit_days=21)
    session.flush()


def ensure_cancelled_supplier_bill(session: Session, rng: random.Random, ctx: SeedContext) -> None:
    """S4: Neha has an October bill from Kanpur Plastics, whose GSTIN is cancelled."""
    from sqlmodel import select
    from app.models import InvoiceRow
    sup = ctx.neha_suppliers["Kanpur Plastics"]
    exists = session.exec(select(InvoiceRow).where(InvoiceRow.supplier_id == sup.id,
                                                   InvoiceRow.invoice_date >= date(2026, 10, 1))).first()
    if not exists:
        create_invoice(session, rng, ctx.neha.id, sup, catalog.ITEMS["cleaning"], "KP-4417", date(2026, 10, 14), 24_000.0)
