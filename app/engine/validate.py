from datetime import timedelta

from app.engine import gstin
from app.engine.hsn_rates import EFFECTIVE_FROM, allowed_rates
from app.engine.issues import Issue
from app.models.schemas import Invoice

TOLERANCE = 1.0  # rupees
DUPLICATE_WINDOW_DAYS = 3


def validate_invoice(inv: Invoice, previous: list[Invoice] | None = None) -> list[Issue]:
    """Pure checks on one extracted bill. `previous` = already-filed invoices of the same merchant."""
    issues: list[Issue] = []
    if inv.bill_type == "gst_invoice":
        issues += _check_gstin(inv)
        issues += _check_tax_type(inv)
        issues += _check_tax_maths(inv)
        issues += _check_hsn_rates(inv)
    issues += _check_line_maths(inv)
    issues += _check_grand_total(inv)
    issues += _check_duplicate(inv, previous or [])
    return issues


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def _check_gstin(inv: Invoice) -> list[Issue]:
    g = inv.supplier_gstin
    if g and gstin.is_valid(g):
        return []
    return [Issue("gstin_invalid", "high", "Supplier GSTIN looks wrong; input tax credit at risk.",
                  "GSTIN galat lagta hai; input tax credit khatre mein hai.", field="supplier_gstin")]


def _is_intra_state(inv: Invoice) -> bool | None:
    if not (inv.supplier_gstin and inv.buyer_gstin):
        return None
    return gstin.state_code(inv.supplier_gstin) == gstin.state_code(inv.buyer_gstin)


def _check_tax_type(inv: Invoice) -> list[Issue]:
    intra = _is_intra_state(inv)
    if intra is None:
        return []
    out = []
    for i, li in enumerate(inv.line_items):
        wrong = (li.igst > 0) if intra else (li.cgst > 0 or li.sgst > 0)
        if wrong:
            out.append(Issue("wrong_tax_type", "warn",
                             f"Line {i + 1}: {'IGST' if intra else 'CGST/SGST'} charged but supply is "
                             f"{'intra' if intra else 'inter'}-state.",
                             f"Line {i + 1}: tax ka type galat hai.", line_index=i))
    return out


def _check_line_maths(inv: Invoice) -> list[Issue]:
    out = []
    for i, li in enumerate(inv.line_items):
        if li.qty is not None and li.rate is not None and not _close(li.qty * li.rate, li.taxable_value):
            out.append(Issue("line_total_mismatch", "warn",
                             f"Line {i + 1}: qty x rate = {li.qty * li.rate:.2f}, bill shows {li.taxable_value:.2f}.",
                             f"Line {i + 1} ka total match nahi karta.", line_index=i))
    return out


def _check_tax_maths(inv: Invoice) -> list[Issue]:
    out = []
    for i, li in enumerate(inv.line_items):
        if li.gst_rate is None:
            continue
        expected = li.taxable_value * li.gst_rate / 100
        if not _close(expected, li.cgst + li.sgst + li.igst):
            out.append(Issue("tax_computed_wrong", "warn",
                             f"Line {i + 1}: expected tax {expected:.2f}, bill shows {li.cgst + li.sgst + li.igst:.2f}.",
                             f"Line {i + 1} par tax galat joda gaya hai.", line_index=i))
    return out


def _check_hsn_rates(inv: Invoice) -> list[Issue]:
    if inv.invoice_date < EFFECTIVE_FROM:
        return []
    out = []
    for i, li in enumerate(inv.line_items):
        allowed = allowed_rates(li.hsn)
        if allowed is not None and li.gst_rate is not None and li.gst_rate not in allowed:
            exp = "/".join(f"{r:g}%" for r in sorted(allowed))
            out.append(Issue("hsn_rate_mismatch", "warn",
                             f"Line {i + 1}: HSN {li.hsn} is normally taxed at {exp}, bill charges {li.gst_rate:g}%.",
                             f"Is item par GST rate alag hona chahiye ({exp}).", field="gst_rate", line_index=i))
    return out


def _check_grand_total(inv: Invoice) -> list[Issue]:
    expected = sum(li.taxable_value for li in inv.line_items) + inv.tax_total + inv.round_off
    if _close(expected, inv.grand_total):
        return []
    return [Issue("total_mismatch", "warn",
                  f"Lines + tax + round-off = {expected:.2f}, bill total is {inv.grand_total:.2f}.",
                  "Bill ka total match nahi karta.", field="grand_total")]


def _check_duplicate(inv: Invoice, previous: list[Invoice]) -> list[Issue]:
    window = timedelta(days=DUPLICATE_WINDOW_DAYS)
    for p in previous:
        if p.supplier_name != inv.supplier_name:
            continue
        same_no = p.invoice_no == inv.invoice_no
        same_amount_near = p.grand_total == inv.grand_total and abs(p.invoice_date - inv.invoice_date) <= window
        if same_no or same_amount_near:
            return [Issue("possible_duplicate", "high",
                          f"Possible duplicate of invoice {p.invoice_no} dated {p.invoice_date}.",
                          f"Yeh bill {p.invoice_no} ({p.invoice_date}) ka duplicate lag raha hai.", field="invoice_no")]
    return []
