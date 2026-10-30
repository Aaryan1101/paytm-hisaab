import io
from datetime import date

import pytest
from PIL import Image, ImageOps

from app.ai import confidence, invoice_mapper, preprocess
from app.ai.extract import InvoiceExtractor
from app.ai.invoice_mapper import ExtractionError, map_invoice, to_date, to_float
from app.ai.structuring import LlmStructurer, _parse_json
from app.engine.issues import Issue
from tests.fakes import SHARMA_BILL, FakeChat, FakeDocAI, text


def jpeg(size=(3000, 2000), color=(200, 180, 150), orientation=None) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


# ---- preprocess
def test_large_image_is_downscaled():
    out = Image.open(io.BytesIO(preprocess.preprocess_image(jpeg())))
    assert max(out.size) == 1600


def test_small_image_not_upscaled():
    out = Image.open(io.BytesIO(preprocess.preprocess_image(jpeg((800, 600)))))
    assert out.size == (800, 600)


def test_exif_rotation_applied():
    out = Image.open(io.BytesIO(preprocess.preprocess_image(jpeg((800, 400), orientation=6))))
    assert out.size == (400, 800)


def test_pdf_passes_through_untouched():
    data, ctype, name = preprocess.prepare(b"%PDF-1.4 fake")
    assert data == b"%PDF-1.4 fake" and ctype == "application/pdf" and name.endswith(".pdf")


def test_image_prepared_as_jpeg():
    _, ctype, name = preprocess.prepare(jpeg((400, 300)))
    assert ctype == "image/jpeg" and name.endswith(".jpg")


def test_garbage_bytes_raise():
    with pytest.raises(Exception):
        preprocess.preprocess_image(b"not an image")


# ---- parsing helpers
@pytest.mark.parametrize("raw,expected", [("₹18,640.00", 18640.0), ("1,12,400", 112400.0), (5, 5.0), ("abc", None),
                                          (None, None), ("", None), ("-250.5", -250.5)])
def test_to_float(raw, expected):
    assert to_float(raw) == expected


@pytest.mark.parametrize("raw,expected", [("28/10/2026", date(2026, 10, 28)), ("2026-10-28", date(2026, 10, 28)),
                                          ("28-Oct-2026", date(2026, 10, 28)), ("28 October 2026", date(2026, 10, 28)),
                                          ("1/2/2026", date(2026, 2, 1)), ("garbage", None), (None, None)])
def test_to_date_is_day_first(raw, expected):
    assert to_date(raw) == expected


# ---- mapper
def test_maps_printed_bill():
    m = map_invoice(SHARMA_BILL)
    inv = m.invoice
    assert inv.invoice_no == "ST-2291" and inv.invoice_date == date(2026, 10, 28) and inv.due_date == date(2026, 11, 4)
    assert len(inv.line_items) == 2 and inv.grand_total == 12180.0 and m.derived == set()


def test_missing_required_fields_raise():
    raw = {**SHARMA_BILL, "invoice_no": None, "grand_total": None}
    with pytest.raises(ExtractionError) as e:
        map_invoice(raw)
    assert set(e.value.missing) == {"invoice_no", "grand_total"}


def test_missing_totals_derived_from_lines_and_flagged():
    raw = {**SHARMA_BILL, "taxable_total": None, "tax_total": None}
    m = map_invoice(raw)
    assert m.invoice.taxable_total == 11600.0 and m.invoice.tax_total == 580.0
    assert m.derived == {"taxable_total", "tax_total"}


def test_credit_note_detected_from_title():
    assert map_invoice({**SHARMA_BILL, "document_title": "CREDIT NOTE"}).invoice.bill_type == "credit_note"


def test_handwritten_without_gstin_is_kachcha_with_synthetic_number():
    raw = {"supplier_name": "Local Dairy", "is_handwritten": True, "invoice_date": "30/10/2026", "grand_total": "3,450",
           "line_items": [{"description": "Milk", "taxable_value": 3450}]}
    m = map_invoice(raw)
    assert m.invoice.bill_type == "kachcha" and m.invoice.invoice_no == "KACHCHA-20261030-3450"
    assert "invoice_no" in m.derived and m.handwritten


def test_lines_without_amount_are_dropped_and_counted():
    raw = {**SHARMA_BILL, "line_items": SHARMA_BILL["line_items"] + [{"description": "smudged"}, "junk"]}
    assert map_invoice(raw).dropped_lines == 2


def test_gstin_kept_exactly_as_printed_even_if_wrong():
    assert map_invoice({**SHARMA_BILL, "supplier_gstin": " 09ABCDE1234F1ZZ "}).invoice.supplier_gstin == "09ABCDE1234F1ZZ"


# ---- confidence
def test_confidence_levels():
    m = map_invoice({**SHARMA_BILL, "taxable_total": None})
    conf = confidence.score_fields(m.invoice, [], m.derived, handwritten=False)
    assert conf["invoice_no"] == 0.95 and conf["taxable_total"] == 0.5 and conf["supplier_gstin"] == 0.0


def test_handwritten_scores_below_threshold():
    m = map_invoice(SHARMA_BILL)
    conf = confidence.score_fields(m.invoice, [], set(), handwritten=True)
    assert conf["grand_total"] < confidence.THRESHOLD


def test_validation_issue_lowers_matching_field():
    m = map_invoice(SHARMA_BILL)
    issues = [Issue("total_mismatch", "warn", "x", "x")]
    assert confidence.score_fields(m.invoice, issues, set(), False)["grand_total"] == 0.5


def test_low_confidence_lists_unsure_but_not_absent_optionals():
    m = map_invoice(SHARMA_BILL)
    conf = confidence.score_fields(m.invoice, [Issue("total_mismatch", "warn", "x", "x")], set(), False)
    low = confidence.low_confidence(conf, m.invoice)
    assert low == ["grand_total"]  # supplier_gstin is absent (0.0) but optional: not a question


# ---- extractor
def test_extractor_runs_docai_with_prepared_image():
    docai = FakeDocAI(SHARMA_BILL)
    out = InvoiceExtractor(docai).extract(jpeg((900, 600)))
    assert out.invoice.invoice_no == "ST-2291" and docai.calls[0]["content_type"] == "image/jpeg"


def test_extractor_pdf_sent_as_pdf():
    docai = FakeDocAI(SHARMA_BILL)
    InvoiceExtractor(docai).extract(b"%PDF-1.7 x")
    assert docai.calls[0]["content_type"] == "application/pdf"


def test_extract_from_text_uses_llm():
    chat = FakeChat([text('```json\n{"supplier_name":"A","invoice_no":"1","invoice_date":"01/10/2026","grand_total":100}\n```')])
    out = InvoiceExtractor(FakeDocAI({}), LlmStructurer(chat)).extract_from_text("OCR TEXT")
    assert out.invoice.grand_total == 100
    assert "Never guess" in chat.calls[0]["messages"][0]["content"]


def test_extract_from_text_without_structurer_raises():
    with pytest.raises(RuntimeError):
        InvoiceExtractor(FakeDocAI({})).extract_from_text("x")


def test_parse_json_variants():
    assert _parse_json('noise {"a": 1} tail') == {"a": 1}
    with pytest.raises(ValueError):
        _parse_json("no json here")
