"""Per-field confidence from deterministic signals (presence, validation results, handwriting)."""
from app.engine.issues import Issue
from app.models.schemas import Invoice

THRESHOLD = 0.8
BASE, HANDWRITTEN, DERIVED, SUSPECT = 0.95, 0.75, 0.5, 0.5
FIELDS = ("supplier_name", "supplier_gstin", "invoice_no", "invoice_date", "due_date", "grand_total", "taxable_total", "tax_total")
_SUSPECT_BY_ISSUE = {"gstin_invalid": "supplier_gstin", "total_mismatch": "grand_total", "line_total_mismatch": "taxable_total",
                     "tax_computed_wrong": "tax_total"}


def score_fields(inv: Invoice, issues: list[Issue], derived: set[str], handwritten: bool) -> dict[str, float]:
    base = HANDWRITTEN if handwritten else BASE
    out = {}
    for f in FIELDS:
        value = getattr(inv, f)
        out[f] = 0.0 if value in (None, "") else (DERIVED if f in derived else base)
    for issue in issues:
        field = _SUSPECT_BY_ISSUE.get(issue.code)
        if field and out[field] > SUSPECT:
            out[field] = SUSPECT
    return out


def low_confidence(conf: dict[str, float], inv: Invoice) -> list[str]:
    """Fields the merchant should confirm: present but unsure. Absent optional fields are not questions."""
    return [f for f, c in conf.items() if 0 < c < THRESHOLD or (c == 0 and f in ("invoice_no", "grand_total"))]
