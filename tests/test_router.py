import pytest

from app.ai.router import Route, route


@pytest.mark.parametrize("text,expected", [
    ("Is hafte kitna dena hai?", Route("get_dues", {"period": "week"})),
    ("aaj kitna dena hai", Route("get_dues", {"period": "today"})),
    ("is mahine kitna dena hai", Route("get_dues", {"period": "month"})),
    ("What do I owe this week?", Route("get_dues", {"period": "week"})),
    ("Sharma ko kitna dena hai?", Route("get_dues", {"period": "week", "supplier": "sharma"})),
    ("Sharma ka hisaab", Route("get_supplier_ledger", {"supplier": "sharma"})),
    ("ledger of Agarwal Dairy", Route("get_supplier_ledger", {"supplier": "agarwal dairy"})),
    ("Paise kab kam padenge?", Route("forecast_cash")),
    ("cash forecast dikhao", Route("forecast_cash")),
    ("CA ke liye report bhejo", Route("export_purchase_register")),
    ("mera Hisaab Score kitna hai", Route("get_hisaab_score")),
    ("credit offer dikhao", Route("get_credit_offer")),
    ("restock ke liye paise chahiye", Route("get_credit_offer")),
    ("koi alert hai?", Route("list_alerts")),
    ("IMS mein kya karna hai", Route("ims_suggestions")),
    ("Sharma ko paanch hazaar cash diye", Route("log_cash_payment", {"supplier": "sharma", "amount": 5000})),
    ("Agarwal dairy ko teen hazaar cash diye", Route("log_cash_payment", {"supplier": "agarwal dairy", "amount": 3000})),
    ("paid Gupta 2500 cash", Route("log_cash_payment", {"supplier": "gupta", "amount": 2500})),
])
def test_retailer_phrases(text, expected):
    assert route(text, "retailer") == expected


@pytest.mark.parametrize("text", ["hello", "kya haal hai", "", "thank you"])
def test_chitchat_has_no_route(text):
    assert route(text, "retailer") is None


def test_cash_phrase_without_amount_is_not_routed_as_payment():
    r = route("Sharma ko cash diye", "retailer")
    assert r is None or r.tool != "log_cash_payment"


@pytest.mark.parametrize("text,expected", [
    ("kaun kitna dena hai", Route("get_receivables")),
    ("who owes me money", Route("get_receivables")),
    ("overdue retailers dikhao", Route("get_receivables")),
    ("reminders bhejo", Route("draft_reminders", {"language": "hi"})),
    ("draft reminders in english", Route("draft_reminders", {"language": "en"})),
    ("settlement match karo", Route("match_settlements")),
    ("credit limit for Ramesh General Store", Route("suggest_credit_limit", {"retailer": "ramesh general store"})),
])
def test_distributor_phrases(text, expected):
    assert route(text, "distributor") == expected


def test_distributor_does_not_get_retailer_routes():
    assert route("Paise kab kam padenge?", "distributor") is None


# ---- amounts keep their separators ("5,000" must not become 5)
@pytest.mark.parametrize("phrase,amount", [("Sharma ko 5,000 cash diye", 5000), ("Agarwal ko 1,12,400 cash diye", 112400),
                                           ("Sharma ko 2.5 lakh cash diye", 250000), ("Sharma ko 12,500.50 cash diye", 12500.5)])
def test_numeric_amounts_with_separators_are_parsed_whole(phrase, amount):
    assert route(phrase, "retailer").args["amount"] == amount


def test_punctuation_outside_numbers_is_still_ignored():
    assert route("Is hafte kitna dena hai?!", "retailer") == Route("get_dues", {"period": "week"})


from app.ai.router import needs_router


def test_needs_router_for_unrecorded_facts():
    cash = Route("log_cash_payment", {"supplier": "x", "amount": 1})
    assert needs_router(cash, [("get_dues", {})]) and needs_router(cash, [])
    assert not needs_router(cash, [("get_dues", {}), ("log_cash_payment", {})])
    assert not needs_router(Route("get_dues"), []) and not needs_router(None, [])


def test_needs_router_when_the_model_drops_the_supplier_scope():
    scoped = Route("get_dues", {"period": "week", "supplier": "sharma"})
    assert needs_router(scoped, [("get_dues", {"period": "week"})])
    assert not needs_router(scoped, [("get_dues", {"supplier": "Sharma"})])
    assert not needs_router(scoped, [("get_supplier_ledger", {"supplier": "Sharma"})])   # a different sensible tool is fine
    assert not needs_router(scoped, [])                                                    # no call at all is handled elsewhere
    assert not needs_router(Route("get_dues", {"period": "week"}), [("get_dues", {"period": "week"})])
