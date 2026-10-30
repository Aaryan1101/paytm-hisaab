"""Decides which supplier a payment went to, using VPA, saved aliases, then fuzzy name match."""
from rapidfuzz import fuzz

from app.engine.reconcile.types import PaymentIn, SupplierRef

FUZZY_MIN_SCORE = 75.0  # token_set_ratio; spec's 85 misses abbreviations like "SHARMA TRDRS LKO" (80)
FUZZY_MIN_LEAD = 10.0   # best candidate must beat the runner-up by this much, else we don't guess


def resolve(payment: PaymentIn, suppliers: list[SupplierRef]) -> tuple[int | None, float | None]:
    """Return (supplier_id, fuzzy_score). fuzzy_score is None for exact resolutions."""
    if payment.supplier_id is not None:
        return payment.supplier_id, None
    if payment.payee_vpa:
        for s in suppliers:
            if s.payee_vpa and s.payee_vpa.lower() == payment.payee_vpa.lower():
                return s.id, None
    if not payment.payee_name:
        return None, None
    name = payment.payee_name.casefold().strip()
    for s in suppliers:
        if name in {n.casefold().strip() for n in (s.name, *s.aliases)}:
            return s.id, None
    return _fuzzy(name, suppliers)


def _fuzzy(name: str, suppliers: list[SupplierRef]) -> tuple[int | None, float | None]:
    scored = sorted(
        ((max(fuzz.token_set_ratio(name, n.casefold()) for n in (s.name, *s.aliases)), s.id) for s in suppliers),
        reverse=True,
    )
    if not scored or scored[0][0] < FUZZY_MIN_SCORE:
        return None, None
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if scored[0][0] - runner_up < FUZZY_MIN_LEAD:
        return None, None
    return scored[0][1], scored[0][0]
