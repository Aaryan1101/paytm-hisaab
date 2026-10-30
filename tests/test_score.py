from app.engine.score import ScoreInputs, compute_factors, compute_score


def inputs(**kw):
    base = dict(weekly_collections=[100.0] * 12, invoices_total=20, invoices_on_time=20, payments_total=20,
                payments_matched=20, history_days=180, top_supplier_share=0.1)
    return ScoreInputs(**{**base, **kw})


def test_perfect_merchant_scores_high():
    r = compute_score(inputs(weekly_collections=[100.0] * 8 + [130.0] * 4))
    assert r.score >= 850 and len(r.reasons) == 3


def test_empty_merchant_scores_floor_region():
    r = compute_score(inputs(weekly_collections=[], invoices_total=0, invoices_on_time=0, payments_total=0,
                             payments_matched=0, history_days=0, top_supplier_share=1.0))
    assert 300 <= r.score < 450


def test_score_bounds():
    assert 300 <= compute_score(inputs()).score <= 900


def test_discipline_drives_score():
    good = compute_score(inputs()).score
    bad = compute_score(inputs(invoices_on_time=5)).score
    assert good - bad >= 100


def test_volatile_collections_lower_stability():
    f = compute_factors(inputs(weekly_collections=[10, 300, 20, 280, 15, 310, 5, 290, 12, 305, 8, 299]))
    assert f["stability"] < 0.3


def test_growth_neutral_with_short_history():
    assert compute_factors(inputs(weekly_collections=[100.0] * 3))["growth"] == 0.5


def test_reason_text_uses_percentage():
    r = compute_score(inputs(invoices_on_time=18))
    disc = next(x for x in compute_score(inputs(invoices_on_time=18), top_n=5).reasons if x.factor == "discipline")
    assert "90%" in disc.text_hi and "90%" in disc.text_en
    assert r.reasons[0].impact >= r.reasons[-1].impact


def test_negative_reason_flagged():
    rs = compute_score(inputs(invoices_on_time=2), top_n=5).reasons
    assert next(x for x in rs if x.factor == "discipline").positive is False
