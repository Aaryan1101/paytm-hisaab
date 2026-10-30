from datetime import date, timedelta

from app.engine.forecast import build_forecast, inflow_std, weekday_means

TODAY = date(2026, 10, 31)  # Saturday


def flat_history(amount=10_000.0, weeks=8):
    return {TODAY - timedelta(days=i): amount for i in range(weeks * 7)}


def no_festival(_d):
    return 1.0


def test_weekday_means_flat():
    assert set(weekday_means(flat_history(), TODAY).values()) == {10_000.0}


def test_missing_days_count_as_zero():
    h = {TODAY: 7000.0}
    assert weekday_means(h, TODAY)[TODAY.weekday()] == 7000.0 / 8


def test_std_zero_for_flat_history():
    assert inflow_std(flat_history(), TODAY) == 0


def test_no_shortfall_when_inflow_covers_dues():
    f = build_forecast(TODAY, 50_000, flat_history(), [(TODAY + timedelta(days=3), 20_000)], multiplier=no_festival)
    assert f.shortfall_date is None and f.shortfall_amount == 0 and len(f.days) == 14


def test_shortfall_on_due_cluster():
    dues = [(date(2026, 11, 5), 80_000)]
    f = build_forecast(TODAY, 20_000, flat_history(), dues, multiplier=no_festival)
    # Nov 1..5: balance 20k + 5*10k - 80k = -10k; buffer 10k -> shortfall 20k on Nov 5
    assert f.shortfall_date == date(2026, 11, 5)
    assert f.shortfall_amount == 20_000
    assert f.first_below_date == date(2026, 11, 5)


def test_overdue_dues_hit_first_day():
    f = build_forecast(TODAY, 100_000, flat_history(), [(date(2026, 10, 1), 30_000)], multiplier=no_festival)
    assert f.days[0].outflow == 30_000


def test_festival_multiplier_applied():
    f = build_forecast(TODAY, 0, flat_history(), [], multiplier=lambda d: 2.0)
    assert f.days[0].inflow == 20_000


def test_other_spend_and_band():
    h = {TODAY - timedelta(days=i): (5000.0 if i % 2 else 15000.0) for i in range(56)}
    f = build_forecast(TODAY, 0, h, [], other_daily_spend=1000, multiplier=no_festival)
    assert f.days[0].outflow == 1000
    assert f.days[0].low < f.days[0].balance < f.days[0].high
