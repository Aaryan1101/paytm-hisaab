"""Seeds the whole demo dataset, and resets the database to it quickly."""
import random
from datetime import date, timedelta

from sqlalchemy import text
from sqlmodel import Session, SQLModel, select

from app import clock
from app.engine import forecast as forecast_engine
from app.models import PaymentOut
from app.seed import catalog, collections, history, ims_seed, retailers, scenarios
from app.seed.context import SeedContext
from app.seed.parties import seed_parties
from app.services import dues_service, reconcile_service, settlement_service

SEED = 42
HISTORY_START = date(2026, 8, 1)
THURSDAY_SHORTFALL = 38_000.0  # demo target: Ramesh is Rs 38,000 short on Thursday


def reset_tables(session: Session) -> None:
    names = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    else:
        for table in reversed(SQLModel.metadata.sorted_tables):
            session.execute(table.delete())
    session.flush()
    session.expunge_all()


def seed_all(session: Session) -> SeedContext:
    rng = random.Random(SEED)
    today = clock.today()
    ctx = SeedContext()
    seed_parties(session, rng, ctx)

    ramesh_cat = {n: c for n, c, _a, _l in catalog.RAMESH_SUPPLIERS}
    history.generate_history(session, rng, ctx.ramesh, ctx.ramesh_suppliers, ramesh_cat, HISTORY_START,
                             date(2026, 10, 10), today, (11, 16))
    scenarios.plant_ramesh(session, rng, ctx)
    scenarios.plant_dues(session, rng, ctx)
    collections.generate_collections(session, rng, ctx.ramesh, HISTORY_START, today)
    collections.generate_expenses(session, rng, ctx.ramesh, HISTORY_START, today)

    neha_cat = {n: catalog.NEHA_CATEGORIES[i % len(catalog.NEHA_CATEGORIES)] for i, n in enumerate(ctx.neha_suppliers)}
    history.generate_history(session, rng, ctx.neha, ctx.neha_suppliers, neha_cat, HISTORY_START, date(2026, 10, 24),
                             today, (20, 30), state_by_supplier={n: catalog.NEHA_OUT_OF_STATE.get(n, "09") for n in ctx.neha_suppliers})
    scenarios.ensure_cancelled_supplier_bill(session, rng, ctx)
    collections.generate_collections(session, rng, ctx.neha, HISTORY_START, today)
    collections.generate_expenses(session, rng, ctx.neha, HISTORY_START, today)
    ims_seed.seed_ims(session, rng, ctx)

    retailers.seed_retailer_history(session, rng, ctx, today)
    session.flush()

    for m in (ctx.ramesh, ctx.neha):
        reconcile_service.reconcile_merchant(session, m.id)
    settlement_service.reconcile_distributor(session, ctx.vikas.id)
    _calibrate_opening_balance(session, ctx.ramesh, today)
    _calibrate_opening_balance(session, ctx.neha, today, target_shortfall=None)
    session.flush()
    return ctx


def _calibrate_opening_balance(session: Session, merchant, today: date, target_shortfall: float | None = THURSDAY_SHORTFALL) -> None:
    """Pick a mock bank balance so Ramesh's worst day is exactly the demo shortfall; Neha just gets a comfortable one."""
    from app.services.forecast_service import forecast_inputs
    inputs = forecast_inputs(session, merchant.id, today)
    base = forecast_engine.build_forecast(today, 0.0, **inputs)
    lowest = min(d.balance for d in base.days)
    if target_shortfall is None:
        merchant.opening_balance = round(max(0.0, forecast_engine.DEFAULT_BUFFER - lowest) + 150_000.0, 2)
    else:
        merchant.opening_balance = round(forecast_engine.DEFAULT_BUFFER - target_shortfall - lowest, 2)
    session.add(merchant)
