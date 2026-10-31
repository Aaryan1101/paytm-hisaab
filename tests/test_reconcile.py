from datetime import date

from app.engine.mdr import mdr_for, net_of_mdr
from app.engine.reconcile import CreditNoteIn, InvoiceIn, PaymentIn, SupplierRef, reconcile

SHARMA = SupplierRef(1, "Sharma Traders", aliases=("Sharma",), payee_vpa="sharma@paytm")
DAIRY = SupplierRef(2, "Agarwal Dairy")
SUPPLIERS = [SHARMA, DAIRY]


def inv(id, total, d=date(2026, 10, 1), supplier=1, no=None):
    return InvoiceIn(id, supplier, no or f"ST-{id}", d, total)


def pay(id, amount, d=date(2026, 10, 10), **kw):
    return PaymentIn(id, amount, d, **kw)


def test_reference_match_has_full_confidence():
    r = reconcile([inv(1, 5000, no="ST-2291")], [pay(1, 5000, remark="inv ST-2291", payee_vpa="x@y")], SUPPLIERS)
    assert r.matches[0].method == "reference" and r.matches[0].confidence == 1.0
    assert r.invoice_status[1] == "paid"


def test_exact_match():
    r = reconcile([inv(1, 18640)], [pay(1, 18640, supplier_id=1)], SUPPLIERS)
    assert [m.method for m in r.matches] == ["exact"] and r.invoice_status[1] == "paid"


def test_exact_outside_window_falls_to_partial():
    r = reconcile([inv(1, 5000, d=date(2026, 1, 1))], [pay(1, 5000, supplier_id=1)], SUPPLIERS)
    assert r.matches[0].method == "partial"


def test_s6_one_payment_clears_two_invoices():
    invoices = [inv(1, 18640), inv(2, 12860), inv(3, 7000)]
    r = reconcile(invoices, [pay(1, 31500, supplier_id=1)], SUPPLIERS)
    assert {m.invoice_id for m in r.matches} == {1, 2}
    assert all(m.method == "many_to_one" for m in r.matches)
    assert r.invoice_status == {1: "paid", 2: "paid", 3: "open"}


def test_partial_payment_goes_oldest_first():
    invoices = [inv(1, 10000, d=date(2026, 9, 1)), inv(2, 10000, d=date(2026, 10, 1))]
    r = reconcile(invoices, [pay(1, 6000, d=date(2026, 10, 5), supplier_id=1)], SUPPLIERS)
    assert r.invoice_status == {1: "part_paid", 2: "open"}
    assert not [a for a in r.alerts]  # 40% gap is a partial payment, not a short payment


def test_s2_short_payment_with_expected_credit_note():
    note = CreditNoteIn(9, supplier_id=1, amount=2300, status="expected", against_invoice_id=1)
    r = reconcile([inv(1, 42300)], [pay(1, 40000, supplier_id=1)], SUPPLIERS, [note])
    assert r.invoice_status[1] == "paid"
    assert r.alerts[0].type == "missing_credit_note" and r.alerts[0].amount == 2300
    assert r.credit_applications[0].credit_note_id == 9


def test_received_credit_note_closes_without_alert():
    note = CreditNoteIn(9, 1, 2300, "received", 1)
    r = reconcile([inv(1, 42300)], [pay(1, 40000, supplier_id=1)], SUPPLIERS, [note])
    assert r.invoice_status[1] == "paid" and r.alerts == []


def test_short_payment_without_note_raises_alert():
    r = reconcile([inv(1, 42300)], [pay(1, 40000, supplier_id=1)], SUPPLIERS)
    assert r.invoice_status[1] == "part_paid" and r.alerts[0].type == "missing_credit_note"


def test_s7_fuzzy_payee_resolves_with_low_confidence():
    r = reconcile([inv(1, 8000)], [pay(1, 8000, payee_name="SHARMA TRDRS LKO")], SUPPLIERS)
    assert r.fuzzy_suggestions[0].supplier_id == 1
    assert r.matches[0].confidence < 0.9


def test_fuzzy_refuses_to_guess_when_ambiguous():
    twins = [SupplierRef(1, "Sharma Traders"), SupplierRef(3, "Sharma Trader")]
    r = reconcile([inv(1, 8000)], [pay(1, 8000, payee_name="SHARMA TRDRS")], twins)
    assert r.fuzzy_suggestions == [] and r.unmatched_payment_ids == [1]


def test_vpa_resolves_supplier_without_fuzzy_flag():
    r = reconcile([inv(1, 8000)], [pay(1, 8000, payee_vpa="Sharma@paytm")], SUPPLIERS)
    assert r.matches[0].confidence == 0.95 and r.fuzzy_suggestions == []


def test_unknown_payee_stays_unmatched():
    r = reconcile([inv(1, 8000)], [pay(1, 8000, payee_name="Random Person")], SUPPLIERS)
    assert r.unmatched_payment_ids == [1] and r.unpaid_invoice_ids == [1]


def test_mdr_rules():
    assert mdr_for(42300) == 169.2 and net_of_mdr(42300) == 42130.8
    assert mdr_for(2000) == 0 and mdr_for(500000) == 300 and mdr_for(42300, exempt=True) == 0


# ---- credit notes tied to a bill (pass 0)
def test_received_note_reduces_an_unpaid_bill():
    note = CreditNoteIn(9, supplier_id=1, amount=2000, status="received", against_invoice_id=1)
    r = reconcile([inv(1, 10_000)], [pay(1, 8_000, supplier_id=1)], SUPPLIERS, [note])
    assert [m.method for m in r.matches] == ["exact"] and r.invoice_status[1] == "paid"
    assert r.credit_applications[0].amount == 2000 and r.alerts == []


def test_received_note_alone_leaves_the_remainder_still_owed():
    note = CreditNoteIn(9, 1, 2000, "received", 1)
    r = reconcile([inv(1, 10_000)], [], SUPPLIERS, [note])
    assert r.invoice_status[1] == "part_paid" and r.unpaid_invoice_ids == [1]  # part-settled by the note, 8,000 still owed
    assert r.credit_applications[0].amount == 2000


def test_note_larger_than_the_bill_is_capped():
    note = CreditNoteIn(9, 1, 50_000, "received", 1)
    r = reconcile([inv(1, 10_000)], [], SUPPLIERS, [note])
    assert r.credit_applications[0].amount == 10_000 and r.invoice_status[1] == "paid"


def test_expected_note_is_not_applied_to_an_unpaid_bill():
    r = reconcile([inv(1, 10_000)], [], SUPPLIERS, [CreditNoteIn(9, 1, 2000, "expected", 1)])
    assert r.credit_applications == [] and r.invoice_status[1] == "open"


def test_applied_notes_are_reapplied_every_run():
    note = CreditNoteIn(9, 1, 2300, "applied", 1)
    r = reconcile([inv(1, 42_300)], [pay(1, 40_000, supplier_id=1)], SUPPLIERS, [note])
    assert r.invoice_status[1] == "paid" and r.alerts == []


def test_a_note_is_never_applied_twice():
    note = CreditNoteIn(9, 1, 2300, "received", 1)
    r = reconcile([inv(1, 42_300)], [pay(1, 40_000, supplier_id=1)], SUPPLIERS, [note])
    assert len(r.credit_applications) == 1
