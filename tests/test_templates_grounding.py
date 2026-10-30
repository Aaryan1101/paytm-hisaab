import pytest

from app.ai import grounding, templates

DUES = {"period": "week", "total": 112400, "total_display": "₹1,12,400", "count": 5, "items": [
    {"supplier": "Gupta Oil Mills", "amount": 19800, "amount_display": "₹19,800", "due_date": "2026-11-03", "invoices": ["GO-5531"]},
    {"supplier": "Sharma Traders", "amount": 42300, "amount_display": "₹42,300", "due_date": "2026-11-04", "invoices": ["ST-2302"]}]}
FORECAST = {"shortfall": True, "weekday": "Thursday", "shortfall_date": "2026-11-05", "shortfall_amount": 38000, "shortfall_display": "₹38,000"}


# ---- templates
def test_dues_text_lists_suppliers_and_total():
    out = templates.render("get_dues", DUES, "hi", "whatsapp")
    assert "₹1,12,400" in out and "• Gupta Oil Mills ₹19,800 (03/11)" in out and out.startswith("Is hafte 5 suppliers")


def test_dues_voice_is_one_sentence_with_spoken_amount():
    out = templates.render("get_dues", DUES, "hi", "voice")
    assert "1 lakh 12 hazaar" in out and "\n" not in out and "sabse pehle Gupta Oil Mills" in out


def test_dues_english():
    assert templates.render("get_dues", DUES, "en", "app").startswith("This week you owe ₹1,12,400")


def test_empty_dues():
    assert "koi dues nahi" in templates.render("get_dues", {**DUES, "items": [], "count": 0}, "hi")


def test_forecast_shortfall_text_and_voice():
    assert "Thursday" in templates.render("forecast_cash", FORECAST, "hi", "app") and "₹38,000" in templates.render("forecast_cash", FORECAST, "hi", "app")
    assert "38 hazaar" in templates.render("forecast_cash", FORECAST, "hi", "voice")


def test_forecast_no_shortfall():
    assert "kami nahi" in templates.render("forecast_cash", {"shortfall": False}, "hi")


def test_credit_ineligible_and_eligible():
    assert "nahi hai" in templates.render("get_credit_offer", {"eligible": False, "reason": "score low"}, "hi")
    ok = {"eligible": True, "limit": 50000, "limit_display": "₹50,000", "tenure_days": 60}
    assert "₹50,000" in templates.render("get_credit_offer", ok, "hi") and "50 hazaar" in templates.render("get_credit_offer", ok, "hi", "voice")


def test_errors_are_friendly_not_raw():
    out = templates.render("get_dues", {"error": "not_found", "message": "No supplier"}, "hi")
    assert "nahi mila" in out and "No supplier" not in out
    assert "try" in templates.render("get_dues", {"error": "internal", "message": "x"}, "en")


def test_unknown_tool_has_generic_ack():
    assert templates.render("mystery", {"ok": 1}, "en") == "Done."


@pytest.mark.parametrize("tool,result", [
    ("get_supplier_ledger", {"supplier": "Sharma", "balance_display": "₹73,800", "open_issues": ["x"]}),
    ("get_hisaab_score", {"score": 780, "reasons": [{"text_hi": "a", "text_en": "b"}]}),
    ("list_alerts", {"count": 1, "alerts": [{"message_hi": "a", "message_en": "b"}]}),
    ("log_cash_payment", {"supplier": "Agarwal", "amount_display": "₹3,000"}),
    ("draft_payment", {"supplier": "Sharma", "amount_display": "₹42,300"}),
    ("export_purchase_register", {"month": "2026-10", "url": "http://x"}),
    ("get_receivables", {"retailers": 40, "total_overdue_display": "₹9", "top": []}),
    ("ims_suggestions", {"counts": {"accept": 1, "reject": 2, "pending": 3}}),
    ("draft_reminders", {"count": 4}),
])
@pytest.mark.parametrize("lang", ["hi", "en"])
def test_every_renderer_produces_text(tool, result, lang):
    assert templates.render(tool, result, lang, "app").strip()


# ---- grounding
def test_numbers_from_tool_result_pass():
    assert grounding.is_grounded("Is hafte ₹1,12,400 dena hai, Sharma ₹42,300.", [DUES])


def test_invented_number_fails():
    assert not grounding.is_grounded("Is hafte ₹1,25,000 dena hai.", [DUES])


def test_spoken_rounding_is_tolerated():
    assert grounding.is_grounded("Is hafte 1 lakh 12 hazaar dena hai.", [DUES])
    assert grounding.is_grounded("Sharma ko 42 hazaar dena hai.", [DUES])


def test_small_numbers_not_checked():
    assert grounding.is_grounded("5 suppliers ko dena hai, 3 din mein.", [DUES])


def test_user_supplied_number_is_allowed():
    assert grounding.is_grounded("₹5,000 cash note kar liya.", [{"status": "ok"}], user_text="Sharma ko 5000 cash diye")


def test_no_tool_results_any_big_number_fails():
    assert not grounding.is_grounded("Aapko ₹18,000 dena hai.", [])


def test_text_without_numbers_always_passes():
    assert grounding.is_grounded("Koi dikkat nahi hai.", [])


def test_lakh_notation_checked():
    assert not grounding.is_grounded("Aapko 3 lakh dena hai.", [DUES])
