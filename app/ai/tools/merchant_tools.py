"""Tool handlers for retailers and wholesalers. Each returns plain JSON-able data computed by services/engines."""
from datetime import date, datetime

from sqlmodel import select

from app.ai.money_format import inr
from app.ai.tools.context import ToolContext
from app.engine.validate import validate_invoice
from app.models import InvoiceRow, Match
from app.services import (credit_note_service, credit_service, dues_service, forecast_service, ims_service,
                          invoice_loader, ledger_service, payment_service, register_export_service, score_service)
from app.services.errors import Invalid, NotFound
from app.services.supplier_lookup import find_supplier

LEDGER_TAIL = 8
IMS_PREVIEW = 10


def _supplier(ctx: ToolContext, name: str):
    sup = find_supplier(ctx.session, ctx.merchant_id, name)
    if sup is None:
        raise NotFound(f"No supplier matching '{name}'")
    return sup


def get_dues(ctx: ToolContext, period: str = "week", supplier: str | None = None) -> dict:
    sid = _supplier(ctx, supplier).id if supplier else None
    dues = dues_service.get_dues(ctx.session, ctx.merchant_id, ctx.today, period, sid)
    return {"period": period, "total": dues.total, "total_display": inr(dues.total), "count": len(dues.items),
            "items": [{"supplier": i.supplier_name, "amount": i.amount, "amount_display": inr(i.amount),
                       "due_date": i.next_due.isoformat(), "invoices": i.invoice_nos} for i in dues.items]}


def get_supplier_ledger(ctx: ToolContext, supplier: str) -> dict:
    ledger = ledger_service.supplier_ledger(ctx.session, ctx.merchant_id, _supplier(ctx, supplier).id)
    return {"supplier": ledger.supplier_name, "balance_due": ledger.balance_due, "balance_display": inr(ledger.balance_due),
            "recent": [{"date": e.day.isoformat(), "kind": e.kind, "ref": e.ref, "amount": e.amount,
                        "balance": e.balance, "status": e.status} for e in ledger.entries[-LEDGER_TAIL:]],
            "open_issues": [a.message_en for a in ledger.open_issues]}


def list_alerts(ctx: ToolContext, type: str | None = None) -> dict:
    from app.services import alert_service
    alerts = alert_service.list_alerts(ctx.session, ctx.merchant_id, type)
    return {"count": len(alerts), "alerts": [{"id": a.id, "type": a.type, "severity": a.severity, "message_en": a.message_en,
                                              "message_hi": a.message_hi, "invoice_id": a.invoice_id} for a in alerts]}


def explain_invoice(ctx: ToolContext, invoice_id: int) -> dict:
    row = ctx.session.get(InvoiceRow, invoice_id)
    if row is None or row.merchant_id != ctx.merchant_id:
        raise NotFound("Invoice not found")
    issues = validate_invoice(invoice_loader.to_schema(ctx.session, row))
    matches = ctx.session.exec(select(Match).where(Match.invoice_id == invoice_id)).all()
    return {"invoice_no": row.invoice_no, "total": row.grand_total, "total_display": inr(row.grand_total),
            "status": row.status, "settled": row.amount_settled, "remaining": dues_service.remaining(row),
            "issues": [{"code": i.code, "message_en": i.message_en, "message_hi": i.message_hi} for i in issues],
            "matches": [{"amount": m.amount_applied, "method": m.method, "confidence": m.confidence} for m in matches]}


def log_cash_payment(ctx: ToolContext, supplier: str, amount: float, date: str | None = None) -> dict:
    sup = _supplier(ctx, supplier)
    when = datetime.combine(_parse_date(date), ctx.now.time()) if date else ctx.now
    pay = payment_service.log_cash_payment(ctx.session, ctx.merchant_id, sup.id, float(amount), when)
    return {"pending_payment_id": pay.id, "supplier": sup.name, "amount": pay.amount, "amount_display": inr(pay.amount),
            "status": "needs_confirmation"}


def request_credit_note(ctx: ToolContext, invoice_id: int, amount: float) -> dict:
    note = credit_note_service.request_credit_note(ctx.session, ctx.notifier, ctx.merchant_id, invoice_id, float(amount), ctx.today)
    return {"credit_note_id": note.id, "amount": note.amount, "amount_display": inr(note.amount), "status": "requested"}


def forecast_cash(ctx: ToolContext, days: int = 14) -> dict:
    f = forecast_service.get_forecast(ctx.session, ctx.merchant_id, ctx.today, int(days))
    out = {"days": len(f.days), "safety_buffer": f.buffer, "shortfall": f.shortfall_amount > 0,
           "meaning": "shortfall_amount is the extra cash needed on shortfall_date to keep the safety buffer"}
    if f.shortfall_date:
        out.update(shortfall_date=f.shortfall_date.isoformat(), weekday=f.shortfall_date.strftime("%A"),
                   shortfall_amount=f.shortfall_amount, shortfall_display=inr(f.shortfall_amount))
    return out


def get_hisaab_score(ctx: ToolContext) -> dict:
    r = score_service.get_score(ctx.session, ctx.merchant_id, ctx.today).result
    return {"score": r.score, "reasons": [{"text_en": x.text_en, "text_hi": x.text_hi, "positive": x.positive} for x in r.reasons]}


def get_credit_offer(ctx: ToolContext, purpose: str | None = None) -> dict:
    decision, report = credit_service.preview(ctx.session, ctx.merchant_id, ctx.today)
    out = {"eligible": decision.eligible, "reason": decision.reason, "score": report.result.score, "illustrative": True}
    if decision.eligible:
        out.update(limit=decision.limit, limit_display=inr(decision.limit), apr_min=decision.apr_min, apr_max=decision.apr_max,
                   tenure_days=decision.tenure_days, next_step="Open the Cash & Credit screen in the app to give consent and accept")
    return out


def draft_payment(ctx: ToolContext, supplier: str, amount: float, source: str = "bank") -> dict:
    sup = _supplier(ctx, supplier)
    d = payment_service.draft_payment(ctx.session, ctx.merchant_id, sup.id, float(amount), source)
    return {"draft_id": d.id, "supplier": sup.name, "amount": d.amount, "amount_display": inr(d.amount), "source": d.source,
            "upi_link": d.upi_link, "status": "needs_confirmation"}


def ims_suggestions(ctx: ToolContext, month: str | None = None) -> dict:
    month = month or ctx.today.strftime("%Y-%m")
    report = ims_service.get_ims(ctx.session, ctx.merchant_id, month)
    attention = [e for e in report.entries if e.action != "accept"]
    return {"month": month, "counts": report.counts(), "missing_from_ims": len(report.missing),
            "needs_attention": [{"supplier": e.supplier_name, "invoice_no": e.invoice_no, "action": e.action,
                                 "reason_en": e.reason_en, "reason_hi": e.reason_hi} for e in attention[:IMS_PREVIEW]]}


def export_purchase_register(ctx: ToolContext, month: str | None = None) -> dict:
    month = month or ctx.today.strftime("%Y-%m")
    name, text = register_export_service.purchase_register_csv(ctx.session, ctx.merchant_id, month)
    if ctx.media is None:
        raise Invalid("File storage is not configured")
    stored = ctx.media.save(text.encode(), "csv", "reports")
    return {"month": month, "file_name": name, "url": stored.url, "rows": max(len(text.strip().splitlines()) - 1, 0)}


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise Invalid("Date must be YYYY-MM-DD") from e


HANDLERS = {f.__name__: f for f in (get_dues, get_supplier_ledger, list_alerts, explain_invoice, log_cash_payment,
                                    request_credit_note, forecast_cash, get_hisaab_score, get_credit_offer,
                                    draft_payment, ims_suggestions, export_purchase_register)}
