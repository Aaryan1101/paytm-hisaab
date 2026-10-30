from app.engine.credit import decide


def ok(**kw):
    base = dict(score=700, history_days=120, avg_monthly_collections=450_000, shortfall=38_000, has_fraud_flag=False)
    return decide(**{**base, **kw})


def test_s5_offer_is_fifty_thousand():
    d = ok()
    assert d.eligible and d.limit == 50_000 and d.tenure_days == 60 and d.apr_min < d.apr_max


def test_low_score_rejected():
    d = ok(score=550)
    assert not d.eligible and "below" in d.reason


def test_short_history_rejected():
    assert not ok(history_days=60).eligible


def test_fraud_flag_rejected():
    assert not ok(has_fraud_flag=True).eligible


def test_no_shortfall_no_offer():
    assert not ok(shortfall=0).eligible


def test_limit_capped_by_monthly_collections():
    assert ok(avg_monthly_collections=50_000).limit == 15_000


def test_limit_capped_at_max():
    assert ok(shortfall=2_000_000, avg_monthly_collections=10_000_000).limit == 500_000


def test_better_score_gets_lower_rate():
    assert ok(score=800).apr_min < ok(score=650).apr_min
