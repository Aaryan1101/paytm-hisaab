"""Sharma Traders' retailers: invoices issued by the distributor and the UPI receipts that settle them."""
import random
from datetime import date, datetime, time, timedelta

from sqlmodel import Session

from app.engine.mdr import mdr_for
from app.models import CollectionIn
from app.seed import catalog
from app.seed.context import SeedContext
from app.seed.invoice_builder import create_invoice
from app.seed.payments import utr

# (share of retailers, days-to-pay range, probability an invoice is never paid)
PROFILES = {"good": ((3, 10), 0.0), "average": ((15, 30), 0.1), "poor": ((40, 70), 0.5)}
PROFILE_ORDER = ["good"] * 16 + ["average"] * 14 + ["poor"] * 9


def seed_retailer_history(session: Session, rng: random.Random, ctx: SeedContext, today: date) -> None:
    others = [r for r in ctx.retailers if r.id != ctx.ramesh.id]
    for retailer, profile in zip(others, PROFILE_ORDER):
        days_range, unpaid_p = PROFILES[profile]
        sharma = ctx.retailer_sharma[retailer.id]
        for _ in range(rng.randint(2, 4)):
            d = date(2026, 8, 15) + timedelta(days=rng.randint(0, 60))
            total = float(rng.randint(60, 600) * 100)
            inv = create_invoice(session, rng, retailer.id, sharma, catalog.ITEMS["fmcg"],
                                 f"ST-{rng.randint(1000, 2290)}", d, total, source="distributor")
            pay_date = d + timedelta(days=rng.randint(*days_range))
            if rng.random() < unpaid_p or pay_date >= today:
                continue
            mdr = mdr_for(total)
            session.add(CollectionIn(merchant_id=ctx.vikas.id, payer_merchant_id=retailer.id, amount=total,
                                     received_at=datetime.combine(pay_date, time(15, 0)),
                                     payer_vpa=f"merchant{retailer.id}@paytm", mdr_amount=mdr,
                                     net_amount=round(total - mdr, 2), utr=utr(rng)))
        session.flush()
