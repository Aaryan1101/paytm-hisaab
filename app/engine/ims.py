"""GST IMS suggestions: accept / reject / pending per inward invoice, with reasons. Pure rules."""
from dataclasses import dataclass

TOLERANCE = 1.0


@dataclass(frozen=True)
class ImsEntryIn:
    id: int
    supplier_gstin: str
    invoice_no: str
    taxable: float
    tax: float
    supplier_status: str = "active"  # active | cancelled | not_filing
    not_purchased: bool = False      # merchant said these goods were never bought


@dataclass(frozen=True)
class BillIn:
    id: int
    supplier_gstin: str
    invoice_no: str
    taxable: float
    tax: float
    goods_received: bool = True


@dataclass(frozen=True)
class ImsDecision:
    entry_id: int
    action: str  # accept | reject | pending
    reason_en: str
    reason_hi: str
    itc_risk_alert: bool = False
    bill_id: int | None = None


@dataclass(frozen=True)
class MissingFromIms:
    bill_id: int
    reason_en: str
    reason_hi: str


def _key(gstin: str, no: str) -> tuple[str, str]:
    return gstin.strip().upper(), no.strip().upper()


def _same_amounts(e: ImsEntryIn, b: BillIn) -> bool:
    return abs(e.taxable - b.taxable) <= TOLERANCE and abs(e.tax - b.tax) <= TOLERANCE


def suggest(entries: list[ImsEntryIn], bills: list[BillIn],
            gstins_with_expected_credit_note: set[str] | None = None) -> tuple[list[ImsDecision], list[MissingFromIms]]:
    expected_cn = {g.upper() for g in (gstins_with_expected_credit_note or set())}
    bills_by_key = {_key(b.supplier_gstin, b.invoice_no): b for b in bills}
    seen: set[tuple[str, str]] = set()
    decisions = [_decide(e, bills_by_key, seen, expected_cn) for e in entries]
    in_ims = {_key(e.supplier_gstin, e.invoice_no) for e in entries}
    missing = [MissingFromIms(b.id, "Supplier has not filed this bill in GSTR-1; chase them.",
                              "Supplier ne GSTR-1 mein nahi daala; unse poochhein.")
               for k, b in bills_by_key.items() if k not in in_ims]
    return decisions, missing


def _decide(e: ImsEntryIn, bills_by_key, seen, expected_cn) -> ImsDecision:
    k = _key(e.supplier_gstin, e.invoice_no)
    if e.supplier_status == "cancelled":
        seen.add(k)
        return ImsDecision(e.id, "pending", "Supplier GSTIN is cancelled; input tax credit at risk. Talk to the supplier.",
                           "Supplier ka GSTIN cancel hai; input tax credit khatre mein hai.", True)
    if k in seen:
        return ImsDecision(e.id, "reject", "Duplicate of an invoice already in the list.", "Yeh invoice pehle se list mein hai (duplicate).")
    seen.add(k)
    bill = bills_by_key.get(k)
    if bill is None:
        if e.not_purchased:
            return ImsDecision(e.id, "reject", "Not purchased.", "Yeh maal kharida nahi gaya.")
        return ImsDecision(e.id, "pending", "No matching bill found in your records.", "Aapke records mein is invoice ka bill nahi mila.")
    if not _same_amounts(e, bill):
        return ImsDecision(e.id, "pending", "Amount or tax differs from your bill; ask the supplier for a correction.",
                           "Supplier se correction maangein.", bill_id=bill.id)
    if e.supplier_gstin.upper() in expected_cn:
        return ImsDecision(e.id, "pending", "A credit note is expected from this supplier; wait before accepting.",
                           "Is supplier se credit note aana baaki hai.", bill_id=bill.id)
    if not bill.goods_received:
        return ImsDecision(e.id, "pending", "Goods not yet received.", "Maal abhi mila nahi.", bill_id=bill.id)
    return ImsDecision(e.id, "accept", "Bill and GST portal match.", "Bill aur GST portal match.", bill_id=bill.id)
