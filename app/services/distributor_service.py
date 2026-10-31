"""Distributor dashboard: receivables, retailer reliability, settlements, digital invoices, reminders."""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.channels.base import Notifier
from app.engine import credit_limit
from app.engine.reminder_tone import tone_for
from app.models import CollectionIn, InvoiceLineRow, InvoiceRow, Match, Merchant, Supplier
from app.services import payment_dates, score_service, settlement_service
from app.services.dues_service import remaining
from app.services.errors import Invalid, NotFound

HISTORY_MONTHS = 3
MAX_REMINDER_CHARS = 1000
DRAFT_WORKERS = 4  # measured against Sarvam: 4 workers draft 8 reminders in ~1.2s; 8 workers stalled on a hung connection


@dataclass(frozen=True)
class RetailerRow:
    retailer_id: int
    name: str
    outstanding: float
    overdue_amount: float
    days_overdue: int
    reliability: float
    suggested_limit: float
    reason_en: str
    reason_hi: str


@dataclass(frozen=True)
class MatchedInvoice:
    invoice_no: str
    amount: float
    match_id: int
    confidence: float
    confirmed: bool  # False means "Confirm?": the engine was not sure


@dataclass(frozen=True)
class SettlementRow:
    collection_id: int
    received_at: datetime
    payer_id: int
    payer_name: str
    gross: float
    mdr: float
    net: float
    matched: list[MatchedInvoice]


@dataclass(frozen=True)
class OpenQuery:
    query_id: int
    retailer_id: int
    retailer_name: str
    invoice_id: int
    invoice_no: str
    text: str
    created_at: datetime


@dataclass(frozen=True)
class RetailerInvoice:
    invoice_id: int
    invoice_no: str
    invoice_date: date
    due_date: date | None
    grand_total: float
    amount_settled: float
    status: str
    source: str


@dataclass(frozen=True)
class RetailerDetail:
    summary: "RetailerRow"
    invoices: list[RetailerInvoice]
    receipts: list[SettlementRow]
    open_queries: list[OpenQuery]


@dataclass(frozen=True)
class ReminderDraft:
    retailer_id: int
    retailer_name: str
    amount: float
    days_overdue: int
    tone: str
    text: str


def _stats(session: Session, retailer: Merchant, invoices: list[InvoiceRow], today: date) -> credit_limit.RetailerStats:
    paid_dates = payment_dates.last_payment_dates(session, [i.id for i in invoices if i.status == "paid"])
    days, on_time, counted = [], 0, 0
    for i in invoices:
        if i.id in paid_dates:
            days.append((paid_dates[i.id] - i.invoice_date).days)
            counted += 1
            on_time += paid_dates[i.id] <= i.due_date if i.due_date else 1
        elif i.status != "paid" and i.due_date and i.due_date < today:
            counted += 1
    score = score_service.get_score(session, retailer.id, today).result.score if retailer.share_score else None
    return credit_limit.RetailerStats(
        on_time_rate=on_time / counted if counted else 0.0, avg_days_to_pay=sum(days) / len(days) if days else None,
        avg_monthly_purchase=sum(i.grand_total for i in invoices) / HISTORY_MONTHS, hisaab_score=score,
        invoices_paid=len(days), order_regularity=credit_limit.order_regularity([i.invoice_date for i in invoices]))


def _by_retailer(session: Session, distributor_id: int) -> dict[int, list[InvoiceRow]]:
    out: dict[int, list[InvoiceRow]] = {}
    for inv in settlement_service.distributor_invoices(session, distributor_id):
        out.setdefault(inv.merchant_id, []).append(inv)
    return out


def receivables(session: Session, distributor_id: int, today: date) -> list[RetailerRow]:
    names = {m.id: m for m in session.exec(select(Merchant)).all()}
    rows = []
    for rid, invoices in _by_retailer(session, distributor_id).items():
        unpaid = [i for i in invoices if i.status in ("open", "part_paid")]
        overdue = [i for i in unpaid if i.due_date and i.due_date < today]
        sug = credit_limit.suggest_limit(_stats(session, names[rid], invoices, today))
        rows.append(RetailerRow(rid, names[rid].name, round(sum(remaining(i) for i in unpaid), 2),
                                round(sum(remaining(i) for i in overdue), 2),
                                max(((today - i.due_date).days for i in overdue), default=0),
                                sug.reliability, sug.limit, sug.reason_en, sug.reason_hi))
    rows.sort(key=lambda r: (-r.overdue_amount, -r.outstanding))
    return rows


def retailer_row(session: Session, distributor_id: int, retailer_id: int, today: date) -> RetailerRow:
    for r in receivables(session, distributor_id, today):
        if r.retailer_id == retailer_id:
            return r
    raise NotFound("Retailer has no invoices with this distributor")


def settlements(session: Session, distributor_id: int) -> list[SettlementRow]:
    names = {m.id: m.name for m in session.exec(select(Merchant)).all()}
    invoices = {i.id: i for i in settlement_service.distributor_invoices(session, distributor_id)}
    out = []
    for c in session.exec(select(CollectionIn).where(CollectionIn.merchant_id == distributor_id,
                                                     CollectionIn.payer_merchant_id != None)  # noqa: E711
                          .order_by(CollectionIn.received_at.desc(), CollectionIn.id.desc())).all():
        out.append(SettlementRow(c.id, c.received_at, c.payer_merchant_id, names.get(c.payer_merchant_id, "?"), c.amount,
                                 c.mdr_amount, c.net_amount, _matched_for(session, c, invoices)))
    return out


def _matched_for(session: Session, c: CollectionIn, invoices: dict[int, InvoiceRow]) -> list[MatchedInvoice]:
    """Matches made on the receipt itself, or through the retailer's payment carrying the same UTR."""
    from app.models import PaymentOut
    q = select(Match).where(Match.collection_id == c.id)
    matches = list(session.exec(q).all())
    if not matches and c.utr:
        pay = session.exec(select(PaymentOut).where(PaymentOut.utr == c.utr)).first()
        if pay:
            matches = list(session.exec(select(Match).where(Match.payment_id == pay.id)).all())
    return [MatchedInvoice(invoices[m.invoice_id].invoice_no, m.amount_applied, m.id, m.confidence, m.confirmed)
            for m in matches if m.invoice_id in invoices]


def open_queries(session: Session, distributor_id: int, retailer_id: int | None = None) -> list[OpenQuery]:
    """Questions retailers have asked about bills ("is this a duplicate?") that the distributor has not answered."""
    from app.models import SupplierQuery
    names = {m.id: m.name for m in session.exec(select(Merchant)).all()}
    invoices = {i.id: i for i in settlement_service.distributor_invoices(session, distributor_id)}
    out = []
    for q in session.exec(select(SupplierQuery).where(SupplierQuery.status == "open").order_by(SupplierQuery.id)).all():
        inv = invoices.get(q.invoice_id)
        if inv is None or (retailer_id is not None and q.merchant_id != retailer_id):
            continue
        out.append(OpenQuery(q.id, q.merchant_id, names.get(q.merchant_id, "?"), inv.id, inv.invoice_no, q.text, q.created_at))
    return out


def retailer_detail(session: Session, distributor_id: int, retailer_id: int, today: date) -> RetailerDetail:
    summary = retailer_row(session, distributor_id, retailer_id, today)
    invoices = sorted((i for i in settlement_service.distributor_invoices(session, distributor_id) if i.merchant_id == retailer_id),
                      key=lambda i: (i.invoice_date, i.id), reverse=True)
    return RetailerDetail(
        summary,
        [RetailerInvoice(i.id, i.invoice_no, i.invoice_date, i.due_date, i.grand_total, i.amount_settled, i.status, i.source) for i in invoices],
        [r for r in settlements(session, distributor_id) if r.payer_id == retailer_id],
        open_queries(session, distributor_id, retailer_id))


def issue_invoice(session: Session, notifier: Notifier, distributor_id: int, retailer_id: int, lines: list[dict],
                  today: date, credit_days: int = 14) -> InvoiceRow:
    """Issue a digital invoice: it lands in the retailer's ledger already confirmed, so matching is exact."""
    dist, retailer = session.get(Merchant, distributor_id), session.get(Merchant, retailer_id)
    if dist is None or dist.role != "distributor":
        raise NotFound("Distributor not found")
    sup = session.exec(select(Supplier).where(Supplier.merchant_id == retailer_id,
                                              Supplier.linked_merchant_id == distributor_id)).first()
    if retailer is None or sup is None:
        raise NotFound("Retailer is not linked to this distributor")
    if not lines:
        raise Invalid("An invoice needs at least one line")
    intra = (dist.gstin or "")[:2] == (retailer.gstin or "")[:2]
    built, taxable_total, tax_total = [], 0.0, 0.0
    for l in lines:
        taxable = round(l["qty"] * l["rate"], 2)
        rate = float(l.get("gst_rate", 5))
        tax = round(taxable * rate / 100, 2)
        half = round(tax / 2, 2)
        built.append(dict(description=l["description"], hsn=l.get("hsn"), qty=l["qty"], rate=l["rate"], taxable_value=taxable,
                          gst_rate=rate, cgst=half if intra else 0.0, sgst=half if intra else 0.0, igst=0.0 if intra else tax))
        taxable_total += taxable
        tax_total += tax
    number = 2310 + len([i for i in settlement_service.distributor_invoices(session, distributor_id) if i.source == "distributor_issued"])
    inv = InvoiceRow(merchant_id=retailer_id, supplier_id=sup.id, invoice_no=f"ST-{number}", invoice_date=today,
                     due_date=today + timedelta(days=credit_days), taxable_total=round(taxable_total, 2),
                     tax_total=round(tax_total, 2), grand_total=round(taxable_total + tax_total, 2), bill_type="gst_invoice",
                     source="distributor_issued", confirmed=True)
    session.add(inv)
    session.flush()
    for b in built:
        session.add(InvoiceLineRow(invoice_id=inv.id, **b))
    session.flush()
    notifier.send(retailer_id, f"{dist.name} ne naya bill #{inv.invoice_no} bheja hai: Rs {inv.grand_total:,.0f}, "
                               f"due {inv.due_date:%d %b}.")
    return inv


def draft_reminders(session: Session, distributor_id: int, today: date, drafter: Callable[..., str],
                    retailer_ids: list[int] | None = None, language: str = "hi") -> list[ReminderDraft]:
    dist = session.get(Merchant, distributor_id)
    rows = [r for r in receivables(session, distributor_id, today)
            if r.overdue_amount > 0 and (retailer_ids is None or r.retailer_id in retailer_ids)]

    def draft(r: RetailerRow) -> ReminderDraft:
        tone = tone_for(r.days_overdue)
        text = drafter(retailer_name=r.name, distributor_name=dist.name, amount=r.overdue_amount,
                       days_overdue=r.days_overdue, tone=tone, language=language)
        return ReminderDraft(r.retailer_id, r.name, r.overdue_amount, r.days_overdue, tone, text)

    # Each draft is an independent LLM call (no DB access inside), so run them side by side; order is preserved.
    with ThreadPoolExecutor(max_workers=DRAFT_WORKERS) as pool:
        return list(pool.map(draft, rows))


def apply_edits(drafts: list[ReminderDraft], texts: dict[int, str] | None) -> list[ReminderDraft]:
    """Replace draft texts with the distributor's own edits (keyed by retailer id)."""
    if not texts:
        return drafts
    known = {d.retailer_id for d in drafts}
    unknown = sorted(set(texts) - known)
    if unknown:
        raise Invalid(f"No reminder to edit for retailer(s) {unknown}")
    if any(not t.strip() or len(t) > MAX_REMINDER_CHARS for t in texts.values()):
        raise Invalid(f"Reminder text must be 1-{MAX_REMINDER_CHARS} characters")
    return [replace(d, text=texts[d.retailer_id].strip()) if d.retailer_id in texts else d for d in drafts]


def send_reminders(notifier: Notifier, drafts: list[ReminderDraft]) -> int:
    for d in drafts:
        notifier.send(d.retailer_id, d.text)
    return len(drafts)
