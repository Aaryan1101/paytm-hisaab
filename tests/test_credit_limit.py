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
