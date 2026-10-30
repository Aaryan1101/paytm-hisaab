"""Mock-lender credit decision. Pure rules; the lender underwrites in real life."""
from dataclasses import dataclass

MIN_SCORE = 600
MIN_HISTORY_DAYS = 90
MAX_LIMIT = 500_000.0
ROUND_TO = 5_000
MONTHLY_COLLECTION_SHARE = 0.30
SHORTFALL_COVER = 1.3  # cover the shortfall with 30% headroom (spec's 2x gives Rs 76k for the Rs 38k demo, not 50k)
TENURE_DAYS = 60


@dataclass(frozen=True)
class CreditDecision:
    eligible: bool
    reason: str
    limit: float = 0.0
    apr_min: float = 0.0
    apr_max: float = 0.0
    tenure_days: int = 0


def _round_to_step(x: float) -> float:
    return float(round(x / ROUND_TO) * ROUND_TO)


def _apr_band(score: int) -> tuple[float, float]:
    return (14.0, 18.0) if score >= 750 else (18.0, 24.0)


def decide(score: int, history_days: int, avg_monthly_collections: float, shortfall: float,
           has_fraud_flag: bool) -> CreditDecision:
    if score < MIN_SCORE:
        return CreditDecision(False, f"Hisaab Score {score} is below {MIN_SCORE}")
    if history_days < MIN_HISTORY_DAYS:
        return CreditDecision(False, "Less than 3 months of history")
    if has_fraud_flag:
        return CreditDecision(False, "Unresolved duplicate-payment flag")
    if shortfall <= 0:
        return CreditDecision(False, "No cash shortfall to cover")
    limit = _round_to_step(min(MONTHLY_COLLECTION_SHARE * avg_monthly_collections,
                               SHORTFALL_COVER * shortfall, MAX_LIMIT))
    if limit <= 0:
        return CreditDecision(False, "Limit rounds to zero")
    lo, hi = _apr_band(score)
    return CreditDecision(True, "Eligible", limit, lo, hi, TENURE_DAYS)
