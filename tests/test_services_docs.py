import csv
import io
from datetime import date

import pytest
from sqlmodel import select

from app import clock
from app.channels.db_notifier import DbNotifier
from app.models import Alert, ImsEntry, InvoiceRow, Message, SupplierQuery
from app.services import (alert_service, dues_service, invoice_service, ims_service, message_service,
                          query_service, register_export_service)
from app.services.errors import Invalid, NotApplicable, NotFound

TODAY = clock.today()
MONTH = "2026-10"


# ---- IMS
def test_ims_only_for_regular_gst(seeded):
    s, ctx = seeded
    with pytest.raises(NotApplicable):
        ims_service.get_ims(s, ctx.ramesh.id, MONTH)


def test_ims_report_has_all_three_actions(seeded):
    s, ctx = seeded
    report = ims_service.get_ims(s, ctx.neha.id, MONTH)
    c = report.counts()
    assert c["accept"] > 10 and c["reject"] >= 2 and c["pending"] >= 3


def test_s4_cancelled_supplier_is_pending_with_itc_alert(seeded):
    s, ctx = seeded
    report = ims_service.get_ims(s, ctx.neha.id, MONTH)
    kp = [e for e in report.entries if e.supplier_name == "Kanpur Plastics"]
    assert kp and all(e.action == "pending" and e.itc_risk for e in kp)
    alerts = alert_service.list_alerts(s, ctx.neha.id, "gstin_risk")
    assert alerts and "cancelled" in alerts[0].message_en


def test_bill_missing_from_ims_raises_alert(seeded):
    s, ctx = seeded
    report = ims_service.get_ims(s, ctx.neha.id, MONTH)
    assert len(report.missing) == 1
    assert alert_service.list_alerts(s, ctx.neha.id, "missing_from_ims")


def test_ims_alerts_not_duplicated_on_rerun(seeded):
    s, ctx = seeded
    ims_service.get_ims(s, ctx.neha.id, MONTH)
    ims_service.get_ims(s, ctx.neha.id, MONTH)
    assert len(alert_service.list_alerts(s, ctx.neha.id, "missing_from_ims")) == 1


def test_override_survives_recompute(seeded):
    s, ctx = seeded
    e = ims_service.get_ims(s, ctx.neha.id, MONTH).entries[0]
    ims_service.override_entry(s, ctx.neha.id, e.id, "reject")
    again = ims_service.get_ims(s, ctx.neha.id, MONTH).entries[0]
    assert again.action == "reject" and again.user_override


def test_override_validations(seeded):
    s, ctx = seeded
    e = ims_service.get_ims(s, ctx.neha.id, MONTH).entries[0]
    with pytest.raises(Invalid):
        ims_service.override_entry(s, ctx.neha.id, e.id, "maybe")
    with pytest.raises(NotFound):
        ims_service.override_entry(s, ctx.ramesh.id, e.id, "accept")


def test_approve_all_writes_to_db_only(seeded):
    s, ctx = seeded
    n = ims_service.approve_all(s, ctx.neha.id, MONTH)
    assert n > 20
    assert all(e.approved for e in s.exec(select(ImsEntry).where(ImsEntry.merchant_id == ctx.neha.id)).all())
    assert any(i.ims_action == "accept" for i in s.exec(select(InvoiceRow).where(InvoiceRow.merchant_id == ctx.neha.id)).all())


# ---- invoice confirm / discard
def _unconfirmed(s, ctx, total=5_000.0):
    sup = ctx.ramesh_suppliers["Gupta Oil Mills"]
    inv = InvoiceRow(merchant_id=ctx.ramesh.id, supplier_id=sup.id, invoice_no="GO-9999", invoice_date=date(2026, 10, 30),
                     due_date=date(2026, 11, 13), taxable_total=total, tax_total=0, grand_total=total, bill_type="gst_invoice",
                     source="whatsapp", confirmed=False, raw_json={"invoice_no": "GO-9999", "grand_total": total,
                                                                    "taxable_total": total, "tax_total": 0})
    s.add(inv)
    s.flush()
    return inv


def test_unconfirmed_bill_not_in_dues_until_confirmed(seeded):
    s, ctx = seeded
    on = date(2026, 11, 13)
    base = dues_service.get_dues(s, ctx.ramesh.id, on, "today").total
    inv = _unconfirmed(s, ctx)
    assert dues_service.get_dues(s, ctx.ramesh.id, on, "today").total == base
    invoice_service.confirm_invoice(s, ctx.ramesh.id, inv.id)
    assert dues_service.get_dues(s, ctx.ramesh.id, on, "today").total == base + 5_000


def test_confirm_applies_corrections(seeded):
    s, ctx = seeded
    inv = _unconfirmed(s, ctx)
    invoice_service.confirm_invoice(s, ctx.ramesh.id, inv.id, {"grand_total": 5_500.0, "invoice_date": "2026-10-29"})
    assert inv.grand_total == 5_500.0 and inv.invoice_date == date(2026, 10, 29) and inv.confirmed


def test_confirm_rejects_unknown_field(seeded):
    s, ctx = seeded
    inv = _unconfirmed(s, ctx)
    with pytest.raises(Invalid):
        invoice_service.confirm_invoice(s, ctx.ramesh.id, inv.id, {"status": "paid"})


def test_confirm_scoped_to_merchant(seeded):
    s, ctx = seeded
    inv = _unconfirmed(s, ctx)
    with pytest.raises(NotFound):
        invoice_service.confirm_invoice(s, ctx.neha.id, inv.id)


def test_discard_marks_disputed_and_resolves_alert(seeded):
    s, ctx = seeded
    inv = _unconfirmed(s, ctx)
    alert_service.add_alert(s, ctx.ramesh.id, "possible_duplicate", "high", "dup", "dup", invoice_id=inv.id)
    invoice_service.discard_invoice(s, ctx.ramesh.id, inv.id)
    assert inv.status == "disputed" and not inv.confirmed
    assert alert_service.list_alerts(s, ctx.ramesh.id, "possible_duplicate") == []


def test_extraction_accuracy_metric(seeded):
    s, ctx = seeded
    a = _unconfirmed(s, ctx)
    invoice_service.confirm_invoice(s, ctx.ramesh.id, a.id)
    assert invoice_service.extraction_accuracy(s, ctx.ramesh.id) == 1.0
    b = _unconfirmed(s, ctx, 7_000.0)
    b.invoice_no = "GO-10000"
    b.raw_json = {"invoice_no": "GO-10000", "grand_total": 7_000.0, "taxable_total": 7_000.0, "tax_total": 0}
    invoice_service.confirm_invoice(s, ctx.ramesh.id, b.id, {"grand_total": 7_100.0})
    assert invoice_service.extraction_accuracy(s, ctx.ramesh.id) == pytest.approx(7 / 8)


def test_accuracy_none_without_data(seeded):
    s, ctx = seeded
    assert invoice_service.extraction_accuracy(s, ctx.neha.id) is None


# ---- supplier queries (S1 flow)
def test_ask_supplier_notifies_distributor_with_buttons(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2291")).one()
    q = query_service.ask_supplier(s, DbNotifier(s), ctx.ramesh.id, inv.id)
    msgs = s.exec(select(Message).where(Message.merchant_id == ctx.vikas.id)).all()
    assert "Ramesh General Store ne bill #ST-2291 par sawaal poocha hai" in msgs[-1].text
    assert "Duplicate hai" in msgs[-1].text and q.status == "open"


def test_answer_duplicate_discards_bill_and_tells_retailer(seeded):
    s, ctx = seeded
    inv = _unconfirmed(s, ctx)
    q = query_service.ask_supplier(s, DbNotifier(s), ctx.ramesh.id, inv.id)
    query_service.answer_query(s, DbNotifier(s), q.id, "duplicate")
    assert inv.status == "disputed" and not inv.confirmed
    assert "duplicate" in s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id)).all()[-1].text


def test_answer_new_bill_confirms_it(seeded):
    s, ctx = seeded
    inv = _unconfirmed(s, ctx)
    q = query_service.ask_supplier(s, DbNotifier(s), ctx.ramesh.id, inv.id)
    query_service.answer_query(s, DbNotifier(s), q.id, "new_bill")
    assert inv.confirmed


def test_answer_validations(seeded):
    s, ctx = seeded
    inv = _unconfirmed(s, ctx)
    q = query_service.ask_supplier(s, DbNotifier(s), ctx.ramesh.id, inv.id)
    with pytest.raises(Invalid):
        query_service.answer_query(s, DbNotifier(s), q.id, "maybe")
    query_service.answer_query(s, DbNotifier(s), q.id, "new_bill")
    with pytest.raises(Invalid):
        query_service.answer_query(s, DbNotifier(s), q.id, "duplicate")
    with pytest.raises(NotFound):
        query_service.answer_query(s, DbNotifier(s), 9999, "duplicate")


# ---- export
def test_purchase_register_csv(seeded):
    s, ctx = seeded
    name, text = register_export_service.purchase_register_csv(s, ctx.neha.id, MONTH)
    rows = list(csv.reader(io.StringIO(text)))
    assert name.endswith("2026-10.csv") and rows[0][0] == "Date" and len(rows) > 20
    igst_rows = [r for r in rows[1:] if float(r[7]) > 0]
    assert igst_rows  # the two out-of-state suppliers


def test_register_empty_month_has_header_only(seeded):
    s, ctx = seeded
    _, text = register_export_service.purchase_register_csv(s, ctx.neha.id, "2020-01")
    assert len(text.strip().splitlines()) == 1


# ---- messages / events
def test_event_feed_returns_only_new_soundbox_events(seeded):
    s, ctx = seeded
    a = message_service.push_event(s, ctx.vikas.id, "Rs 2500 prapt hue")
    message_service.log_message(s, ctx.vikas.id, "whatsapp", "out", "ignored")
    b = message_service.push_event(s, ctx.vikas.id, "second")
    assert [m.id for m in message_service.list_events(s, ctx.vikas.id)] == [a.id, b.id]
    assert [m.id for m in message_service.list_events(s, ctx.vikas.id, after_id=a.id)] == [b.id]
