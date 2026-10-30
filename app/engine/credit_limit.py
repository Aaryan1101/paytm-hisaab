"""Distributor-side: reliability of a retailer and the credit limit to offer them."""
from dataclasses import dataclass

MIN_MULT, MAX_MULT = 0.5, 2.0
SLOW_DAYS = 30  # average days-to-pay at or beyond this scores zero on speed


@dataclass(frozen=True)
class RetailerStats:
    on_time_rate: float          # 0..1 share of invoices paid by due date
    avg_days_to_pay: float | None
    avg_monthly_purchase: float
    hisaab_score: int | None = None  # only if the retailer opted in
    invoices_paid: int = 0


@dataclass(frozen=True)
class LimitSuggestion:
    reliability: float  # 0..100
    multiplier: float
    limit: float
    reason_en: str
    reason_hi: str


def reliability(s: RetailerStats) -> float:
    speed = 0.0 if s.avg_days_to_pay is None else max(0.0, 1 - s.avg_days_to_pay / SLOW_DAYS)
    if s.hisaab_score is None:
        score = 0.65 * s.on_time_rate + 0.35 * speed
    else:
        score = 0.5 * s.on_time_rate + 0.3 * speed + 0.2 * (s.hisaab_score - 300) / 600
    return round(100 * max(0.0, min(1.0, score)), 1)


def suggest_limit(s: RetailerStats) -> LimitSuggestion:
    rel = reliability(s)
    mult = round(MIN_MULT + (MAX_MULT - MIN_MULT) * rel / 100, 2)
    days = "no payment history yet" if s.avg_days_to_pay is None else f"pays in {s.avg_days_to_pay:.0f} days on average"
    days_hi = "abhi tak payment history nahi" if s.avg_days_to_pay is None else f"average {s.avg_days_to_pay:.0f} din mein pay karte hain"
    pct = round(s.on_time_rate * 100)
    return LimitSuggestion(
        reliability=rel, multiplier=mult, limit=round(s.avg_monthly_purchase * mult / 1000) * 1000.0,
        reason_en=f"{days.capitalize()}, {pct}% paid on time over {s.invoices_paid} invoices",
        reason_hi=f"{days_hi}, {pct}% bills time par pay hue ({s.invoices_paid} invoices)",
    )
