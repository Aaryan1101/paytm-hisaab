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
