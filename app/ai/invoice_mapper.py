"""Maps Document AI's loose JSON into our strict Invoice schema. Parsing only: no arithmetic on money."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.schemas import Invoice, LineItem

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y",
                 "%b %d, %Y")


class ExtractionError(Exception):
    def __init__(self, missing: list[str]):
        super().__init__("Could not read: " + ", ".join(missing))
        self.missing = missing


@dataclass
class Mapped:
    invoice: Invoice
    derived: set[str] = field(default_factory=set)  # fields we filled in from line items
    dropped_lines: int = 0
    handwritten: bool = False


def to_float(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    cleaned = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def to_date(v) -> date | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _clean(v) -> str | None:
    return str(v).strip() or None if v is not None else None


def _line(raw: dict) -> LineItem | None:
    taxable = to_float(raw.get("taxable_value"))
    if taxable is None or not _clean(raw.get("description")):
        return None
    return LineItem(description=_clean(raw["description"]), hsn=_clean(raw.get("hsn")), qty=to_float(raw.get("qty")),
                    unit=_clean(raw.get("unit")), rate=to_float(raw.get("rate")), taxable_value=taxable,
                    gst_rate=to_float(raw.get("gst_rate")), cgst=to_float(raw.get("cgst")) or 0.0,
                    sgst=to_float(raw.get("sgst")) or 0.0, igst=to_float(raw.get("igst")) or 0.0)


def _bill_type(title: str, gstin: str | None, handwritten: bool, has_tax: bool) -> str:
    t = title.casefold()
    if "credit note" in t or re.search(r"\bcn\b", t):
        return "credit_note"
    if "debit note" in t:
        return "debit_note"
    return "kachcha" if not gstin and (handwritten or not has_tax) else "gst_invoice"


def map_invoice(raw: dict) -> Mapped:
    lines_raw = raw.get("line_items") or []
    lines = [l for l in (_line(r) for r in lines_raw if isinstance(r, dict)) if l]
    derived: set[str] = set()
    total = to_float(raw.get("grand_total"))
    inv_date = to_date(raw.get("invoice_date"))
    gstin = _clean(raw.get("supplier_gstin"))
    handwritten = bool(raw.get("is_handwritten"))
    taxable = to_float(raw.get("taxable_total"))
    tax = to_float(raw.get("tax_total"))
    if taxable is None and lines:
        taxable, _ = round(sum(l.taxable_value for l in lines), 2), derived.add("taxable_total")
    if tax is None and lines:
        tax, _ = round(sum(l.cgst + l.sgst + l.igst for l in lines), 2), derived.add("tax_total")
    bill_type = _bill_type(str(raw.get("document_title") or ""), gstin, handwritten, bool(tax))
    number = _clean(raw.get("invoice_no"))
    if number is None and bill_type == "kachcha" and inv_date and total is not None:
        number, _ = f"KACHCHA-{inv_date:%Y%m%d}-{int(total)}", derived.add("invoice_no")
    missing = [n for n, v in (("invoice_no", number), ("invoice_date", inv_date), ("grand_total", total),
                              ("supplier_name", _clean(raw.get("supplier_name")))) if v is None]
    if missing:
        raise ExtractionError(missing)
    invoice = Invoice(
        supplier_name=_clean(raw["supplier_name"]), supplier_gstin=gstin, buyer_gstin=_clean(raw.get("buyer_gstin")),
        invoice_no=number, invoice_date=inv_date, due_date=to_date(raw.get("due_date")),
        place_of_supply=_clean(raw.get("place_of_supply")), line_items=lines, taxable_total=taxable or 0.0,
        tax_total=tax or 0.0, round_off=to_float(raw.get("round_off")) or 0.0, grand_total=total, bill_type=bill_type)
    return Mapped(invoice, derived, len(lines_raw) - len(lines), handwritten)
