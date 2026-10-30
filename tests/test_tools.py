import json

import pytest
from sqlmodel import select

from app.ai.tools import registry
from app.models import InvoiceRow, PaymentDraft, PaymentOut
from app.storage import MediaStore
from tests.helpers import make_ctx


def run(ctx, name, args=None):
    return registry.execute(name, json.dumps(args or {}), ctx)


# ---- registry safety
def test_unknown_tool(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.ramesh), "nope")["error"] == "unknown_tool"


def test_bad_json_arguments(seeded):
    s, ctx = seeded
    assert registry.execute("get_dues", "{not json", make_ctx(s, ctx.ramesh))["error"] == "bad_arguments"


def test_non_object_arguments(seeded):
    s, ctx = seeded
    assert registry.execute("get_dues", "[1,2]", make_ctx(s, ctx.ramesh))["error"] == "bad_arguments"


def test_missing_required_argument(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.ramesh), "get_supplier_ledger")["error"] == "missing_arguments"


def test_unknown_arguments_are_dropped(seeded):
    s, ctx = seeded
    assert "error" not in run(make_ctx(s, ctx.ramesh), "get_dues", {"period": "week", "evil": "x"})


def test_non_numeric_amount_rejected(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "draft_payment", {"supplier": "Sharma", "amount": "lots"})
    assert r["error"] == "bad_arguments"


def test_string_numbers_are_coerced(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.ramesh), "forecast_cash", {"days": "7"})["days"] == 7


def test_tool_exceptions_become_error_results(seeded, monkeypatch):
    s, ctx = seeded
    from app.ai.tools import merchant_tools
    monkeypatch.setitem(merchant_tools.HANDLERS, "get_dues", lambda c, **k: 1 / 0)
    assert run(make_ctx(s, ctx.ramesh), "get_dues")["error"] == "internal"


def test_roles_get_different_toolsets(seeded):
    names = lambda role: {t["function"]["name"] for t in registry.tool_specs(role)}
    assert "get_receivables" in names("distributor") and "get_dues" not in names("distributor")
    assert "draft_payment" in names("retailer") and "get_receivables" not in names("retailer")


def test_merchant_tool_not_callable_by_distributor(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.vikas), "get_dues")["error"] == "unknown_tool"


# ---- merchant tools
def test_get_dues_week(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "get_dues", {"period": "week"})
    assert r["total"] == 112_400 and r["total_display"] == "₹1,12,400" and r["count"] == 5
    assert r["items"][0]["supplier"] == "Gupta Oil Mills"


def test_get_dues_for_one_supplier_by_fuzzy_name(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "get_dues", {"supplier": "sharma"})
    assert r["total"] == 42_300 and r["items"][0]["invoices"] == ["ST-2302"]


def test_unknown_supplier_is_a_clean_error(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "get_dues", {"supplier": "Zzz Qqq"})
    assert r["error"] == "not_found"


def test_supplier_ledger(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "get_supplier_ledger", {"supplier": "Sharma Traders"})
    assert r["balance_due"] == 73_800 and len(r["recent"]) <= 8 and r["recent"][-1]["balance"] is not None


def test_list_alerts(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "list_alerts")
    assert {a["type"] for a in r["alerts"]} >= {"missing_credit_note", "confirm_payee"}
    assert run(make_ctx(s, ctx.ramesh), "list_alerts", {"type": "missing_credit_note"})["count"] == 1


def test_explain_invoice_s2(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2250")).one()
    r = run(make_ctx(s, ctx.ramesh), "explain_invoice", {"invoice_id": inv.id})
    assert r["status"] == "paid" and r["matches"][0]["amount"] == 40_000 and r["total"] == 42_300


def test_explain_invoice_scoped_to_merchant(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2250")).one()
    assert run(make_ctx(s, ctx.neha), "explain_invoice", {"invoice_id": inv.id})["error"] == "not_found"


def test_s9_cash_payment_logged_pending(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "log_cash_payment", {"supplier": "Agarwal dairy", "amount": 3000})
    assert r["status"] == "needs_confirmation" and r["supplier"] == "Agarwal Dairy" and r["amount_display"] == "₹3,000"
    assert s.get(PaymentOut, r["pending_payment_id"]).confirmed is False


def test_cash_payment_bad_date(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "log_cash_payment", {"supplier": "Agarwal", "amount": 100, "date": "yesterday"})
    assert r["error"] == "invalid"


def test_request_credit_note_tool(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    r = run(make_ctx(s, ctx.ramesh), "request_credit_note", {"invoice_id": inv.id, "amount": 500})
    assert r["status"] == "requested" and r["amount_display"] == "₹500"


def test_s5_forecast_tool(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "forecast_cash")
    assert r["shortfall"] and r["weekday"] == "Thursday" and r["shortfall_amount"] == 38_000


def test_forecast_tool_does_not_expose_raw_balances(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "forecast_cash")
    assert "series" not in r and "lowest_balance" not in r


def test_forecast_without_shortfall_omits_fields(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.neha), "forecast_cash")
    assert r["shortfall"] is False and "shortfall_date" not in r


def test_score_tool(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "get_hisaab_score")
    assert r["score"] >= 600 and len(r["reasons"]) == 3


def test_credit_offer_preview_tool(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.ramesh), "get_credit_offer")
    assert r["eligible"] and r["limit"] == 50_000 and r["illustrative"] and "consent" in r["next_step"]


def test_credit_offer_ineligible_has_reason(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.neha), "get_credit_offer")
    assert r["eligible"] is False and "limit" not in r and r["reason"]


def test_draft_payment_never_executes(seeded):
    s, ctx = seeded
    before = len(s.exec(select(PaymentOut)).all())
    r = run(make_ctx(s, ctx.ramesh), "draft_payment", {"supplier": "Sharma", "amount": 42300})
    assert r["status"] == "needs_confirmation" and r["upi_link"].startswith("upi://pay")
    assert len(s.exec(select(PaymentOut)).all()) == before
    assert s.get(PaymentDraft, r["draft_id"]).status == "drafted"


def test_draft_payment_credit_without_offer_is_error(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.ramesh), "draft_payment", {"supplier": "Sharma", "amount": 100, "source": "credit"})["error"] == "invalid"


def test_ims_tool_for_regular_gst(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.neha), "ims_suggestions", {"month": "2026-10"})
    assert r["counts"]["accept"] > 10 and r["needs_attention"] and r["missing_from_ims"] == 1


def test_ims_tool_not_applicable_to_composition(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.ramesh), "ims_suggestions")["error"] == "not_applicable"


def test_export_register_tool(seeded, tmp_path):
    s, ctx = seeded
    media = MediaStore(str(tmp_path), "http://h")
    r = run(make_ctx(s, ctx.neha, media=media), "export_purchase_register", {"month": "2026-10"})
    assert r["rows"] > 20 and r["url"].startswith("http://h/media/reports/") and any((tmp_path / "reports").iterdir())


def test_export_without_storage_is_error(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.neha), "export_purchase_register")["error"] == "invalid"


# ---- distributor tools
def test_get_receivables(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.vikas), "get_receivables", {"limit": 3})
    assert r["retailers"] == 40 and len(r["top"]) == 3 and r["total_overdue"] > 0


def test_suggest_credit_limit_by_fuzzy_retailer(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.vikas), "suggest_credit_limit", {"retailer": "ramesh general"})
    assert r["retailer"] == "Ramesh General Store" and r["suggested_limit"] > 0 and r["reason_en"]


def test_suggest_credit_limit_unknown_retailer(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.vikas), "suggest_credit_limit", {"retailer": "Nonexistent Emporium"})["error"] == "not_found"


def test_draft_reminders_requires_drafter(seeded):
    s, ctx = seeded
    assert run(make_ctx(s, ctx.vikas), "draft_reminders")["error"] == "invalid"


def test_draft_reminders_does_not_send(seeded):
    s, ctx = seeded
    from app.models import Message
    n = len(s.exec(select(Message)).all())
    r = run(make_ctx(s, ctx.vikas, drafter=lambda **k: f"{k['tone']} reminder"), "draft_reminders")
    assert r["sent"] is False and r["count"] > 0 and r["drafts"][0]["text"].endswith("reminder")
    assert len(s.exec(select(Message)).all()) == n


def test_match_settlements_tool(seeded):
    s, ctx = seeded
    r = run(make_ctx(s, ctx.vikas), "match_settlements")
    assert r["receipts"] and all("gross_display" in x and "mdr_display" in x for x in r["receipts"])
