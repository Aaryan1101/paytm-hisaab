from app.engine.credit_limit import RetailerStats, reliability, suggest_limit
from app.engine.reminder_tone import tone_for


def stats(**kw):
    base = dict(on_time_rate=1.0, avg_days_to_pay=5.0, avg_monthly_purchase=100_000, invoices_paid=6)
    return RetailerStats(**{**base, **kw})


def test_great_retailer_gets_high_multiplier():
    s = suggest_limit(stats())
    assert s.multiplier > 1.7 and s.limit > 170_000


def test_bad_retailer_gets_floor():
    s = suggest_limit(stats(on_time_rate=0.0, avg_days_to_pay=60))
    assert s.multiplier == 0.5 and s.limit == 50_000


def test_no_history_handled():
    s = suggest_limit(stats(on_time_rate=0.0, avg_days_to_pay=None, invoices_paid=0))
    assert "no payment history" in s.reason_en.lower()


def test_score_improves_reliability():
    assert reliability(stats(hisaab_score=850)) > reliability(stats(hisaab_score=400))


def test_reason_mentions_days_and_rate():
    s = suggest_limit(stats(on_time_rate=0.83, avg_days_to_pay=9))
    assert "9 days" in s.reason_en and "83%" in s.reason_en


def test_tone_by_overdue_days():
    assert [tone_for(d) for d in (-2, 0, 3, 7, 8, 30, 31)] == ["friendly", "friendly", "polite", "polite", "firm", "firm", "final"]


# ---- order regularity
from datetime import date, timedelta
from app.engine.credit_limit import order_regularity


def weekly(n, gap=7):
    return [date(2026, 8, 1) + timedelta(days=gap * i) for i in range(n)]


def test_even_ordering_is_fully_regular():
    assert order_regularity(weekly(5)) == 1.0


def test_erratic_ordering_scores_low():
    ds = [date(2026, 8, 1), date(2026, 8, 3), date(2026, 9, 25), date(2026, 9, 26), date(2026, 10, 29)]
    assert order_regularity(ds) < 0.3


def test_too_few_orders_means_unknown_not_zero():
    assert order_regularity(weekly(2)) is None and order_regularity([]) is None
    assert order_regularity([date(2026, 8, 1)] * 3) is None  # all the same day: no gaps to judge


def test_unknown_regularity_leaves_reliability_unchanged():
    assert reliability(stats()) == reliability(stats(order_regularity=None))


def test_regular_reorderers_rate_higher_than_erratic_ones():
    assert reliability(stats(order_regularity=1.0)) > reliability(stats(order_regularity=0.0))
    assert reliability(stats(order_regularity=1.0, hisaab_score=800)) > reliability(stats(order_regularity=0.0, hisaab_score=800))
