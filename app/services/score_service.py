"""Builds Hisaab Score inputs from the ledger and runs the scoring engine."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.engine import score as engine
from app.models import CollectionIn, InvoiceRow, Match, PaymentOut
from app.services import payment_dates

WEEKS = 12


@dataclass(frozen=True)
class ScoreReport:
    result: engine.ScoreResult
    inputs: engine.ScoreInputs


def _weekly_collections(session: Session, merchant_id: int, today: date) -> list[float]:
    start = today - timedelta(days=WEEKS * 7 - 1)
    totals = [0.0] * WEEKS
    for c in session.exec(select(CollectionIn).where(CollectionIn.merchant_id == merchant_id,
                                                     CollectionIn.payer_merchant_id == None,  # noqa: E711
                                                     CollectionIn.received_at >= start)).all():
        idx = (c.received_at.date() - start).days // 7
        if 0 <= idx < WEEKS:
            totals[idx] += c.amount
    return totals


def build_inputs(session: Session, merchant_id: int, today: date) -> engine.ScoreInputs:
    invoices = list(session.exec(select(InvoiceRow).where(
        InvoiceRow.merchant_id == merchant_id, InvoiceRow.confirmed == True,  # noqa: E712
        InvoiceRow.supplier_id != None)).all())  # noqa: E711
    last_paid = payment_dates.last_payment_dates(session, [i.id for i in invoices])
    total = on_time = 0
    for i in invoices:
        if i.status == "paid" and i.id in last_paid:
            total += 1
            on_time += last_paid[i.id] <= i.due_date if i.due_date else 1
        elif i.status != "paid" and i.due_date and i.due_date < today:
            total += 1
    payments = list(session.exec(select(PaymentOut).where(PaymentOut.merchant_id == merchant_id,
                                                          PaymentOut.category == "supplier", PaymentOut.confirmed == True)).all())  # noqa: E712
    matched_ids = {m.payment_id for m in session.exec(select(Match).where(Match.payment_id != None)).all()}  # noqa: E711
    first_dates = [i.invoice_date for i in invoices]
    first_dates += [c.received_at.date() for c in session.exec(select(CollectionIn).where(
        CollectionIn.merchant_id == merchant_id).limit(1000)).all()]
    spend: dict[int, float] = {}
    for i in invoices:
        spend[i.supplier_id] = spend.get(i.supplier_id, 0.0) + i.grand_total
    all_spend = sum(spend.values())
    return engine.ScoreInputs(
        weekly_collections=_weekly_collections(session, merchant_id, today),
        invoices_total=total, invoices_on_time=int(on_time), payments_total=len(payments),
        payments_matched=sum(1 for p in payments if p.id in matched_ids),
        history_days=(today - min(first_dates)).days if first_dates else 0,
        top_supplier_share=max(spend.values()) / all_spend if all_spend else 1.0)


def get_score(session: Session, merchant_id: int, today: date) -> ScoreReport:
    inputs = build_inputs(session, merchant_id, today)
    return ScoreReport(engine.compute_score(inputs), inputs)
