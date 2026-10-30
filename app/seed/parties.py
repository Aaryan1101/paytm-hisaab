"""Creates merchants and their suppliers."""
import random

from sqlmodel import Session

from app.models import Merchant, Supplier
from app.seed import catalog
from app.seed.context import SeedContext
from app.seed.ids import new_gstin, phone, vpa_for


def seed_parties(session: Session, rng: random.Random, ctx: SeedContext) -> None:
    ctx.ramesh = _merchant(session, "Ramesh General Store", "retailer", "composition", "<1.5cr", "9810000001", new_gstin(rng))
    ctx.neha = _merchant(session, "Gupta Wholesale", "wholesaler", "regular", "1.5-10cr", "9810000002", new_gstin(rng))
    ctx.vikas = _merchant(session, "Sharma Traders", "distributor", "regular", "1.5-10cr", "9810000003", new_gstin(rng))
    ctx.vikas.language = "en"
    _ramesh_suppliers(session, rng, ctx)
    _neha_suppliers(session, rng, ctx)
    _retailers(session, rng, ctx)


def _merchant(session, name, role, scheme, band, ph, gstin) -> Merchant:
    m = Merchant(name=name, role=role, gst_scheme=scheme, turnover_band=band, phone=ph, gstin=gstin)
    session.add(m)
    session.flush()
    return m


def _supplier(session, merchant_id, name, gstin, aliases=(), status="active", linked=None, ph=None) -> Supplier:
    s = Supplier(merchant_id=merchant_id, name=name, aliases=list(aliases), gstin=gstin, gstin_status=status,
                 phone=ph, payee_vpa=vpa_for(name), linked_merchant_id=linked)
    session.add(s)
    session.flush()
    return s


def _ramesh_suppliers(session, rng, ctx) -> None:
    for name, _cat, aliases, linked in catalog.RAMESH_SUPPLIERS:
        # Sharma's GSTIN is his own merchant GSTIN so both sides of the network agree
        g = ctx.vikas.gstin if linked else new_gstin(rng)
        ctx.ramesh_suppliers[name] = _supplier(session, ctx.ramesh.id, name, g, aliases,
                                               linked=ctx.vikas.id if linked else None, ph=ctx.vikas.phone if linked else phone(rng))


def _neha_suppliers(session, rng, ctx) -> None:
    for name in catalog.NEHA_SUPPLIER_NAMES:
        state = catalog.NEHA_OUT_OF_STATE.get(name, "09")
        status = "cancelled" if name == "Kanpur Plastics" else "active"
        ctx.neha_suppliers[name] = _supplier(session, ctx.neha.id, name, new_gstin(rng, state), status=status, ph=phone(rng))


def _retailers(session, rng, ctx) -> None:
    firsts, seconds = catalog.RETAILER_NAME_PARTS
    used = set()
    ctx.retailers.append(ctx.ramesh)
    ctx.retailer_sharma[ctx.ramesh.id] = ctx.ramesh_suppliers["Sharma Traders"]
    while len(ctx.retailers) < 40:
        name = f"{rng.choice(firsts)} {rng.choice(seconds)} {rng.choice(catalog.UP_TOWNS)}"
        if name in used:
            continue
        used.add(name)
        r = _merchant(session, name, "retailer", "composition", "<1.5cr", phone(rng), new_gstin(rng))
        ctx.retailers.append(r)
        ctx.retailer_sharma[r.id] = _supplier(session, r.id, "Sharma Traders", ctx.vikas.gstin, ("Sharma",), linked=ctx.vikas.id)
