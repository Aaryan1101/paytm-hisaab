"""Generates ~90 days of purchase history with realistic payment behaviour."""
import random
from datetime import date, timedelta

from sqlmodel import Session

from app.models import Merchant, Supplier
from app.seed import catalog
from app.seed.invoice_builder import create_invoice
from app.seed.payments import record_cash_payment, record_upi_payment


def generate_history(session: Session, rng: random.Random, merchant: Merchant, suppliers: dict[str, Supplier],
                     categories: dict[str, str], start: date, end: date, today: date,
                     every_days: tuple[int, int], state_by_supplier: dict[str, str] | None = None) -> None:
    last_payable = today - timedelta(days=1)
    for name, supplier in suppliers.items():
        pool = catalog.ITEMS[categories[name]]
        intra = (state_by_supplier or {}).get(name, "09") == "09"
        prefix = "".join(c for c in name if c.isupper())[:3] or "INV"
        d = start + timedelta(days=rng.randint(0, every_days[1]))
        seq = rng.randint(100, 900)
        while d <= end:
            seq += 1
            total = float(rng.randint(30, 320) * 100)
            inv = create_invoice(session, rng, merchant.id, supplier, pool, f"{prefix}-{seq}", d, total, intra=intra)
            _pay(session, rng, merchant, supplier, inv.invoice_no, inv.due_date, total, last_payable)
            d += timedelta(days=rng.randint(*every_days))


def _pay(session, rng, merchant, supplier, invoice_no, due, total, last_payable: date) -> None:
    roll = rng.random()
    if roll < 0.88:
        pay_date = due - timedelta(days=rng.randint(0, 4))
    elif roll < 0.96:
        pay_date = due + timedelta(days=rng.randint(2, 10))
    else:
        record_cash_payment(session, merchant.id, supplier, total, min(due, last_payable))
        return
    remark = invoice_no if rng.random() < 0.4 else None
    record_upi_payment(session, rng, merchant.id, supplier, total, min(pay_date, last_payable), remark=remark)
