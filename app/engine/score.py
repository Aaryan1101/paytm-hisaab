"""Hisaab Score (300-900): transparent weighted factors, each scaled 0..1."""
from dataclasses import dataclass
from statistics import mean, pstdev

WEIGHTS = {"stability": 0.30, "discipline": 0.30, "growth": 0.15, "completeness": 0.15, "concentration": 0.10}

# Factor values of the "median merchant" in the seed data; reasons are measured against these.
MEDIAN_FACTORS = {"stability": 0.60, "discipline": 0.70, "growth": 0.50, "completeness": 0.60, "concentration": 0.60}

_TEXT = {
    "stability": ("Your weekly UPI collections are steady", "Aapki weekly UPI collection steady hai",
                  "Your weekly UPI collections swing a lot", "Aapki weekly UPI collection mein utaar-chadhav hai"),
    "discipline": ("You pay {pct}% of bills on time", "Aap {pct}% bills time par pay karte hain",
                   "Only {pct}% of your bills are paid on time", "Sirf {pct}% bills time par pay hue hain"),
    "growth": ("Your collections are growing", "Aapki collection badh rahi hai",
               "Your collections have dipped recently", "Aapki collection haal mein ghati hai"),
    "completeness": ("Most payments are matched to bills", "Zyada tar payments bill se match hain",
                     "Many payments have no matching bill", "Kai payments ka bill match nahi hai"),
    "concentration": ("You buy from many suppliers, so risk is spread", "Aap kai suppliers se khareedte hain",
                      "Too much of your buying is from one supplier", "Ek hi supplier se bahut zyada khareed hai"),
}


@dataclass(frozen=True)
class ScoreInputs:
    weekly_collections: list[float]  # oldest to newest, up to 12 weeks
    invoices_total: int
    invoices_on_time: int
    payments_total: int
    payments_matched: int
    history_days: int
    top_supplier_share: float  # 0..1 share of purchases from the biggest supplier


@dataclass(frozen=True)
class Reason:
    factor: str
    positive: bool
    text_en: str
    text_hi: str
    impact: float


@dataclass(frozen=True)
class ScoreResult:
    score: int
    factors: dict[str, float]
    reasons: list[Reason]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_factors(i: ScoreInputs) -> dict[str, float]:
    weeks = i.weekly_collections
    avg = mean(weeks) if weeks else 0.0
    stability = _clamp(1 - pstdev(weeks) / avg) if avg > 0 and len(weeks) > 1 else 0.0
    recent, prior = weeks[-4:], weeks[-8:-4]
    if recent and prior and sum(prior) > 0:
        growth = _clamp(0.5 + (sum(recent) / sum(prior) - 1))
    else:
        growth = 0.5
    discipline = i.invoices_on_time / i.invoices_total if i.invoices_total else 0.0
    matched_share = i.payments_matched / i.payments_total if i.payments_total else 0.0
    completeness = _clamp(0.7 * matched_share + 0.3 * min(i.history_days / 180, 1.0))
    return {"stability": stability, "discipline": _clamp(discipline), "growth": growth,
            "completeness": completeness, "concentration": _clamp(1 - i.top_supplier_share)}


def _reason(factor: str, value: float, delta: float) -> Reason:
    good_en, good_hi, bad_en, bad_hi = _TEXT[factor]
    positive = delta >= 0
    en, hi = (good_en, good_hi) if positive else (bad_en, bad_hi)
    pct = round(value * 100)
    return Reason(factor, positive, en.format(pct=pct), hi.format(pct=pct), round(WEIGHTS[factor] * abs(delta), 4))


def compute_score(i: ScoreInputs, top_n: int = 3) -> ScoreResult:
    factors = compute_factors(i)
    score = round(300 + 600 * sum(WEIGHTS[k] * v for k, v in factors.items()))
    reasons = sorted((_reason(k, v, v - MEDIAN_FACTORS[k]) for k, v in factors.items()),
                     key=lambda r: r.impact, reverse=True)[:top_n]
    return ScoreResult(score, factors, reasons)
