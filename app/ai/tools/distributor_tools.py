"""Tool handlers for distributors."""
from app.ai.money_format import inr
from app.ai.tools.context import ToolContext
from app.models import Merchant
from app.services import distributor_service, settlement_service
from app.services.errors import Invalid, NotFound
from app.engine.name_match import similarity

MIN_NAME_SCORE = 70.0


def _row(r) -> dict:
    return {"retailer": r.name, "outstanding": r.outstanding, "outstanding_display": inr(r.outstanding),
            "overdue": r.overdue_amount, "overdue_display": inr(r.overdue_amount), "days_overdue": r.days_overdue,
            "reliability": r.reliability, "suggested_limit": r.suggested_limit, "suggested_limit_display": inr(r.suggested_limit),
            "reason_en": r.reason_en, "reason_hi": r.reason_hi}


def _find_retailer(ctx: ToolContext, name: str):
    rows = distributor_service.receivables(ctx.session, ctx.merchant_id, ctx.today)
    best = max(rows, key=lambda r: similarity(name, r.name), default=None)
    if best is None or similarity(name, best.name) < MIN_NAME_SCORE:
        raise NotFound(f"No retailer matching '{name}'")
    return best


def get_receivables(ctx: ToolContext, limit: int = 10) -> dict:
    rows = distributor_service.receivables(ctx.session, ctx.merchant_id, ctx.today)
    return {"retailers": len(rows), "total_outstanding": round(sum(r.outstanding for r in rows), 2),
            "total_overdue": round(sum(r.overdue_amount for r in rows), 2),
            "total_overdue_display": inr(sum(r.overdue_amount for r in rows)), "top": [_row(r) for r in rows[:int(limit)]]}


def draft_reminders(ctx: ToolContext, retailer: str | None = None, language: str = "hi") -> dict:
    if ctx.reminder_drafter is None:
        raise Invalid("Reminder drafting is not configured")
    ids = [_find_retailer(ctx, retailer).retailer_id] if retailer else None
    drafts = distributor_service.draft_reminders(ctx.session, ctx.merchant_id, ctx.today, ctx.reminder_drafter, ids, language)
    return {"count": len(drafts), "sent": False,
            "drafts": [{"retailer": d.retailer_name, "amount_display": inr(d.amount), "days_overdue": d.days_overdue,
                        "tone": d.tone, "text": d.text} for d in drafts[:10]]}


def match_settlements(ctx: ToolContext) -> dict:
    settlement_service.reconcile_distributor(ctx.session, ctx.merchant_id)
    rows = distributor_service.settlements(ctx.session, ctx.merchant_id)[:10]
    return {"receipts": [{"payer": r.payer_name, "gross": r.gross, "gross_display": inr(r.gross), "mdr": r.mdr,
                          "mdr_display": inr(r.mdr), "net_display": inr(r.net), "matched": [m[0] for m in r.matched],
                          "unmatched": not r.matched} for r in rows]}


def suggest_credit_limit(ctx: ToolContext, retailer: str) -> dict:
    return _row(_find_retailer(ctx, retailer))


HANDLERS = {f.__name__: f for f in (get_receivables, draft_reminders, match_settlements, suggest_credit_limit)}
