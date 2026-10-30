import io
from datetime import date

import pytest
from PIL import Image
from sqlmodel import select

from app.ai.extract import InvoiceExtractor
from app.models import Alert, InvoiceRow, Supplier
from app.services import alert_service, dues_service, ingest_service
from app.services.errors import Unreadable
from app.storage import MediaStore
from tests.fakes import FakeDocAI, s1_bill

IMG = io.BytesIO()
Image.new("RGB", (600, 400), (210, 200, 190)).save(IMG, "JPEG")
PHOTO = IMG.getvalue()


def ingest(s, ctx, raw, merchant=None, media=None):
    return ingest_service.ingest_invoice(s, (merchant or ctx.ramesh).id, PHOTO, "whatsapp", InvoiceExtractor(FakeDocAI(raw)), media)


def test_s1_duplicate_bill_detected_with_original_payment_date(seeded):
    s, ctx = seeded
    r = ingest(s, ctx, s1_bill(ctx.vikas.gstin))
    assert r.duplicate and r.duplicate.invoice_no == "ST-2291" and r.duplicate.paid_on == date(2026, 10, 12)
    assert any(i.code == "possible_duplicate" for i in r.issues)
    row = s.get(InvoiceRow, r.invoice_id)
    assert row.status == "disputed" and not row.confirmed


def test_duplicate_does_not_enter_dues(seeded):
    s, ctx = seeded
    ingest(s, ctx, s1_bill(ctx.vikas.gstin))
    assert dues_service.get_dues(s, ctx.ramesh.id, date(2026, 11, 4), "today").total == 42_300 + 19_800


def test_duplicate_raises_alert_linked_to_invoice(seeded):
    s, ctx = seeded
    r = ingest(s, ctx, s1_bill(ctx.vikas.gstin))
    alerts = alert_service.list_alerts(s, ctx.ramesh.id, "possible_duplicate")
    assert [a.invoice_id for a in alerts] == [r.invoice_id]


def test_clean_new_bill_has_no_issues_and_is_unconfirmed(seeded):
    s, ctx = seeded
    raw = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-3000", "invoice_date": "20/09/2026", "grand_total": 18_640.0}
    r = ingest(s, ctx, raw)
    assert r.duplicate is None and r.issues == [] and r.low_confidence_fields == []
    row = s.get(InvoiceRow, r.invoice_id)
    assert row.status == "open" and not row.confirmed and row.supplier_id == ctx.ramesh_suppliers["Sharma Traders"].id


def test_s3_wrong_gst_rate_flagged_on_line(seeded):
    s, ctx = seeded
    raw = {"document_title": "Tax Invoice", "supplier_name": "Gupta Oil Mills", "supplier_gstin": ctx.ramesh_suppliers["Gupta Oil Mills"].gstin,
           "invoice_no": "GO-7001", "invoice_date": "30/10/2026",
           "line_items": [{"description": "Mustard Oil 1L", "hsn": "1514", "qty": 10, "rate": 100, "taxable_value": 1000,
                           "gst_rate": 18, "cgst": 90, "sgst": 90}],
           "taxable_total": 1000, "tax_total": 180, "grand_total": 1180}
    r = ingest(s, ctx, raw)
    bad = [i for i in r.issues if i.code == "hsn_rate_mismatch"]
    assert bad and bad[0].line_index == 0 and "5%" in bad[0].message_en


def test_invalid_gstin_flagged_and_confidence_lowered(seeded):
    s, ctx = seeded
    raw = {**s1_bill(ctx.vikas.gstin[:-1] + "0"), "invoice_no": "ST-3001", "invoice_date": "30/10/2026"}
    r = ingest(s, ctx, raw)
    assert any(i.code == "gstin_invalid" for i in r.issues)
    assert "supplier_gstin" in r.low_confidence_fields


def test_s8_handwritten_kachcha_bill_tagged_non_gst_and_needs_review(seeded):
    s, ctx = seeded
    raw = {"supplier_name": "Agarwal Dairy", "is_handwritten": True, "invoice_date": "30/10/2026", "grand_total": "3,450",
           "line_items": [{"description": "Milk 1L x 60", "taxable_value": 3450}]}
    r = ingest(s, ctx, raw)
    row = s.get(InvoiceRow, r.invoice_id)
    assert row.bill_type == "kachcha" and row.supplier_id == ctx.ramesh_suppliers["Agarwal Dairy"].id
    assert "grand_total" in r.low_confidence_fields
    assert not [i for i in r.issues if i.code.startswith("gstin")]


def test_unknown_supplier_is_created(seeded):
    s, ctx = seeded
    raw = {**s1_bill(None), "supplier_name": "Brand New Distributors", "invoice_no": "BN-1", "invoice_date": "30/10/2026"}
    r = ingest(s, ctx, raw)
    sup = s.get(Supplier, s.get(InvoiceRow, r.invoice_id).supplier_id)
    assert sup.name == "Brand New Distributors" and sup.merchant_id == ctx.ramesh.id


def test_supplier_matched_by_gstin_even_if_name_differs(seeded):
    s, ctx = seeded
    raw = {**s1_bill(ctx.vikas.gstin), "supplier_name": "M/s SHARMA TRDRS", "invoice_no": "ST-3002", "invoice_date": "30/10/2026"}
    r = ingest(s, ctx, raw)
    assert s.get(InvoiceRow, r.invoice_id).supplier_id == ctx.ramesh_suppliers["Sharma Traders"].id


def test_missing_due_date_defaults_to_two_weeks(seeded):
    s, ctx = seeded
    raw = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-3003", "invoice_date": "30/10/2026", "due_date": None}
    row = s.get(InvoiceRow, ingest(s, ctx, raw).invoice_id)
    assert row.due_date == date(2026, 11, 13)


def test_unreadable_bill_raises_with_missing_fields(seeded):
    s, ctx = seeded
    with pytest.raises(Unreadable) as e:
        ingest(s, ctx, {"supplier_name": "X"})
    assert "invoice_no" in e.value.message


def test_raw_extraction_kept_for_accuracy_metric(seeded):
    s, ctx = seeded
    raw = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-3004", "invoice_date": "30/10/2026"}
    row = s.get(InvoiceRow, ingest(s, ctx, raw).invoice_id)
    assert row.raw_json["invoice_no"] == "ST-3004" and "_docai" in row.raw_json and "field_confidence" in row.raw_json


def test_image_stored_privately(seeded, tmp_path):
    s, ctx = seeded
    media = MediaStore(str(tmp_path), "http://x")
    raw = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-3005", "invoice_date": "30/10/2026"}
    r = ingest(s, ctx, raw, media=media)
    assert r.image_url.startswith("http://x/media/bills/") and len(list((tmp_path / "bills").iterdir())) == 1


def test_lines_persisted(seeded):
    s, ctx = seeded
    raw = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-3006", "invoice_date": "30/10/2026"}
    r = ingest(s, ctx, raw)
    from app.models import InvoiceLineRow
    assert len(s.exec(select(InvoiceLineRow).where(InvoiceLineRow.invoice_id == r.invoice_id)).all()) == 1


def test_media_store_unique_names(tmp_path):
    m = MediaStore(str(tmp_path), "http://h/")
    a, b = m.save(b"1", "wav", "audio"), m.save(b"2", ".wav", "audio")
    assert a.path != b.path and a.url.startswith("http://h/media/audio/") and a.path.read_bytes() == b"1"
