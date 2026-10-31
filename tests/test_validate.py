from datetime import date

from app.engine import gstin
from app.engine.validate import validate_invoice
from app.models.schemas import Invoice, LineItem

SUP = gstin.make("09", "ABCDE1234F")
BUY = gstin.make("09", "PQRST6789K")


def bill(**kw) -> Invoice:
    line = LineItem(description="Oil 1L", hsn="1514", qty=10, rate=100, taxable_value=1000, gst_rate=5, cgst=25, sgst=25)
    base = dict(supplier_name="Sharma Traders", supplier_gstin=SUP, buyer_gstin=BUY, invoice_no="ST-1",
                invoice_date=date(2026, 10, 28), line_items=[line], taxable_total=1000, tax_total=50,
                grand_total=1050, bill_type="gst_invoice")
    return Invoice(**{**base, **kw})


def codes(inv, prev=None):
    return {i.code for i in validate_invoice(inv, prev)}


def test_clean_bill_has_no_issues():
    assert codes(bill()) == set()


def test_bad_gstin():
    assert "gstin_invalid" in codes(bill(supplier_gstin=SUP[:-1] + "0"))


def test_wrong_gst_rate_for_hsn():  # S3
    li = LineItem(description="Oil", hsn="1514", qty=10, rate=100, taxable_value=1000, gst_rate=18, cgst=90, sgst=90)
    assert "hsn_rate_mismatch" in codes(bill(line_items=[li], tax_total=180, grand_total=1180))


def test_igst_on_intra_state():
    li = LineItem(description="Oil", hsn="1514", qty=10, rate=100, taxable_value=1000, gst_rate=5, igst=50)
    assert "wrong_tax_type" in codes(bill(line_items=[li]))


def test_total_mismatch():
    assert "total_mismatch" in codes(bill(grand_total=1100))


def test_duplicate_by_number():  # S1
    assert "possible_duplicate" in codes(bill(), [bill(invoice_date=date(2026, 10, 12))])


def test_kachcha_skips_gst_checks():
    inv = bill(bill_type="kachcha", supplier_gstin=None, buyer_gstin=None)
    assert codes(inv) == set()


def test_hsn_check_skipped_before_gst_2_0():
    li = LineItem(description="Biscuits", hsn="1905", qty=10, rate=100, taxable_value=1000, gst_rate=18, cgst=90, sgst=90)
    inv = bill(line_items=[li], invoice_date=date(2025, 6, 1), tax_total=180, grand_total=1180)
    assert "hsn_rate_mismatch" not in codes(inv)


# ---- wider HSN table
import pytest as _pytest
from app.engine.hsn_rates import ALLOWED_RATES, allowed_rates


def test_hsn_table_covers_the_common_kirana_goods():
    assert len(ALLOWED_RATES) >= 45


@_pytest.mark.parametrize("hsn,rate,ok", [("1902", 5, True), ("1902", 18, False), ("2202", 40, True), ("2202", 5, False),
                                          ("2005", 5, True), ("2105", 18, False), ("3303", 18, True), ("9619", 0, True),
                                          ("1509", 5, True), ("1509", 18, False), ("0713", 0, True), ("2501", 5, False)])
def test_hsn_rate_checks(hsn, rate, ok):
    assert (rate in allowed_rates(hsn)) is ok


def test_unknown_hsn_is_not_checked():
    assert allowed_rates("8517") is None and allowed_rates(None) is None


def test_longer_hsn_codes_match_by_prefix():
    assert allowed_rates("19053100") == {0, 5}


# ---- tax shown only in the totals block (very common on Indian bills)
def totals_only(**kw):
    lines = [LineItem(description="Biscuits", hsn="1905", qty=100, rate=40, taxable_value=4000, gst_rate=5),
             LineItem(description="Soap", hsn="3401", qty=200, rate=38, taxable_value=7600, gst_rate=5)]
    base = dict(line_items=lines, taxable_total=11600, tax_total=580, grand_total=12180)
    return bill(**{**base, **kw})


def test_no_false_alarm_when_tax_is_only_in_the_totals_block():
    assert "tax_computed_wrong" not in codes(totals_only())


def test_wrong_total_tax_is_still_caught_when_lines_carry_no_tax():
    r = [i for i in validate_invoice(totals_only(tax_total=900, grand_total=12500)) if i.code == "tax_computed_wrong"]
    assert len(r) == 1 and r[0].line_index is None and r[0].field == "tax_total" and "580.00" in r[0].message_en


def test_rounding_across_several_lines_is_tolerated():
    lines = [LineItem(description=f"Item {i}", hsn="1905", qty=1, rate=333.33, taxable_value=333.33, gst_rate=5) for i in range(6)]
    inv = bill(line_items=lines, taxable_total=1999.98, tax_total=100.0, grand_total=2099.98)   # 6 x 16.67 = 100.02 vs 100.00
    assert "tax_computed_wrong" not in codes(inv)


def test_per_line_tax_is_still_checked_per_line():
    li = LineItem(description="Oil", hsn="1514", qty=10, rate=100, taxable_value=1000, gst_rate=5, cgst=25, sgst=0)
    r = [i for i in validate_invoice(bill(line_items=[li], tax_total=25, grand_total=1025)) if i.code == "tax_computed_wrong"]
    assert len(r) == 1 and r[0].line_index == 0


def test_lines_without_a_gst_rate_are_not_tax_checked():
    li = LineItem(description="Mystery", taxable_value=1000)
    assert "tax_computed_wrong" not in codes(bill(line_items=[li], taxable_total=1000, tax_total=0, grand_total=1000))


# ---- duplicate detection must survive how bills are really read (found with real Document AI)
def test_duplicate_found_despite_different_capitalisation():
    prev = bill(supplier_name="Sharma Traders", invoice_date=date(2026, 10, 12), supplier_gstin=None, buyer_gstin=None)
    assert "possible_duplicate" in codes(bill(supplier_name="SHARMA TRADERS", supplier_gstin=None, buyer_gstin=None), [prev])


def test_duplicate_found_despite_punctuation_and_a_trailing_ampersand_co():
    prev = bill(supplier_name="Sharma Traders", invoice_date=date(2026, 10, 12), supplier_gstin=None, buyer_gstin=None)
    assert "possible_duplicate" in codes(bill(supplier_name="Sharma Traders & Co.", supplier_gstin=None, buyer_gstin=None), [prev])


def test_name_only_matching_is_a_fallback_extra_location_words_need_a_gstin():
    """Without a GSTIN a name with extra distinctive words ("(Lucknow)") is treated as a different business. Real GST
    bills carry a GSTIN, which is what identifies the supplier."""
    prev = bill(supplier_name="Sharma Traders", invoice_date=date(2026, 10, 12))
    assert "possible_duplicate" in codes(bill(supplier_name="M/s. Sharma Traders (Lucknow)", invoice_date=date(2026, 10, 28)), [prev])


def test_same_gstin_means_same_supplier_whatever_the_name_says():
    prev = bill(supplier_name="Sharma Traders", invoice_date=date(2026, 10, 12))
    assert "possible_duplicate" in codes(bill(supplier_name="S T Wholesale", invoice_date=date(2026, 10, 28)), [prev])


def test_different_gstins_mean_different_suppliers_even_with_the_same_name():
    other = gstin.make("09", "ZZZZZ9999Z")
    prev = bill(supplier_name="Sharma Traders", invoice_date=date(2026, 10, 12), supplier_gstin=other)
    assert "possible_duplicate" not in codes(bill(supplier_name="Sharma Traders"), [prev])


def test_similar_but_different_businesses_are_not_duplicates():
    prev = bill(supplier_name="Sharma Textiles", invoice_date=date(2026, 10, 12), supplier_gstin=None, buyer_gstin=None)
    assert "possible_duplicate" not in codes(bill(supplier_name="Sharma Traders", supplier_gstin=None, buyer_gstin=None), [prev])


def test_a_typo_in_the_name_is_still_the_same_supplier():
    prev = bill(supplier_name="Agarwal Dairy", invoice_date=date(2026, 10, 12), supplier_gstin=None, buyer_gstin=None)
    assert "possible_duplicate" in codes(bill(supplier_name="Agarwal Diary", supplier_gstin=None, buyer_gstin=None), [prev])
