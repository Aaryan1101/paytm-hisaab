from app.engine.ims import BillIn, ImsEntryIn, suggest

G = "09ABCDE1234F1ZX"


def entry(id=1, no="A1", taxable=1000.0, tax=50.0, **kw):
    return ImsEntryIn(id, kw.pop("gstin", G), no, taxable, tax, **kw)


def bill(id=1, no="A1", taxable=1000.0, tax=50.0, **kw):
    return BillIn(id, kw.pop("gstin", G), no, taxable, tax, **kw)


def run(entries, bills, cn=None):
    d, m = suggest(entries, bills, cn)
    return {x.entry_id: x for x in d}, m


def test_match_accepts():
    d, m = run([entry()], [bill()])
    assert d[1].action == "accept" and m == []


def test_tolerance_within_one_rupee():
    assert run([entry(taxable=1000.8)], [bill()])[0][1].action == "accept"


def test_amount_mismatch_pending():
    assert run([entry(taxable=1200)], [bill()])[0][1].action == "pending"


def test_s4_cancelled_gstin_pending_with_alert():
    d = run([entry(supplier_status="cancelled")], [bill()])[0][1]
    assert d.action == "pending" and d.itc_risk_alert


def test_duplicate_entry_rejected():
    d, _ = run([entry(1), entry(2)], [bill()])
    assert d[1].action == "accept" and d[2].action == "reject"


def test_no_bill_not_purchased_rejected():
    assert run([entry(not_purchased=True)], [])[0][1].action == "reject"


def test_no_bill_otherwise_pending():
    assert run([entry()], [])[0][1].action == "pending"


def test_expected_credit_note_pending():
    assert run([entry()], [bill()], {G})[0][1].action == "pending"


def test_goods_not_received_pending():
    assert run([entry()], [bill(goods_received=False)])[0][1].action == "pending"


def test_bill_missing_from_ims_reported():
    _, missing = run([], [bill(7)])
    assert [x.bill_id for x in missing] == [7]


def test_key_is_case_insensitive():
    assert run([entry(no="a1")], [bill(no="A1")])[0][1].action == "accept"
