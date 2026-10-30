from datetime import date, datetime

import pytest
from sqlmodel import select

from app import clock
from app.channels.db_notifier import DbNotifier
from app.models import CollectionIn, CreditNote, InvoiceRow, Message
from app.services import (credit_note_service, demo_service, distributor_service, dues_service, invoice_loader,
                          message_service, payment_dates)
from app.services.errors import Invalid, NotFound

TODAY = clock.today()


# ---- receivables
def test_receivables_cover_all_forty_retailers(seeded):
    s, ctx = seeded
    rows = distributor_service.receivables(s, ctx.vikas.id, TODAY)
    assert len(rows) == 40
    assert rows == sorted(rows, key=lambda r: (-r.overdue_amount, -r.outstanding))


def test_reliability_separates_good_and_poor_retailers(seeded):
    s, ctx = seeded
    rows = distributor_service.receivables(s, ctx.vikas.id, TODAY)
    top, bottom = max(rows, key=lambda r: r.reliability), min(rows, key=lambda r: r.reliability)
    assert top.reliability > 70 and bottom.reliability < 30
    assert top.suggested_limit > bottom.suggested_limit * 0.5 or bottom.suggested_limit >= 0


def test_ramesh_row_has_reason_text(seeded):
    s, ctx = seeded
    row = distributor_service.retailer_row(s, ctx.vikas.id, ctx.ramesh.id, TODAY)
    assert "paid on time" in row.reason_en and row.outstanding > 0 and row.overdue_amount == 0


def test_unknown_retailer_not_found(seeded):
    s, ctx = seeded
    with pytest.raises(NotFound):
        distributor_service.retailer_row(s, ctx.vikas.id, ctx.neha.id, TODAY)


def test_opt_in_score_changes_reliability(seeded):
    s, ctx = seeded
    before = distributor_service.retailer_row(s, ctx.vikas.id, ctx.ramesh.id, TODAY).reliability
    ctx.ramesh.share_score = True
    s.add(ctx.ramesh)
    after = distributor_service.retailer_row(s, ctx.vikas.id, ctx.ramesh.id, TODAY).reliability
    assert after != before


# ---- settlements (S6, S10)
def test_settlements_show_mdr_separately(seeded):
    s, ctx = seeded
    rows = distributor_service.settlements(s, ctx.vikas.id)
    big = [r for r in rows if r.gross > 2000]
    assert big and all(abs(r.gross - r.mdr - r.net) < 0.01 and r.mdr > 0 for r in big)


def test_s6_s10_payment_clears_two_invoices_with_mdr(seeded):
    s, ctx = seeded
    result = demo_service.simulate_payment(s, ctx.ramesh.id)
    assert result.gross == 31_500 and result.mdr == 126 and result.net == 31_374
    assert [m[0] for m in result.matched] == ["ST-2308", "ST-2309"]
    assert result.retailer_reliability_after > result.retailer_reliability_before
    row = distributor_service.settlements(s, ctx.vikas.id)[0]
    assert row.payer_name == "Ramesh General Store" and len(row.matched) == 2


def test_simulate_payment_updates_both_ledgers_and_announces(seeded):
    s, ctx = seeded
    paid_before = dues_service.get_dues(s, ctx.ramesh.id, date(2026, 12, 31), "today").total
    demo_service.simulate_payment(s, ctx.ramesh.id)
    assert dues_service.get_dues(s, ctx.ramesh.id, date(2026, 12, 31), "today").total == paid_before - 31_500
    events = message_service.list_events(s, ctx.vikas.id)
    assert events and "31,500" in events[-1].text and "prapt hue" in events[-1].text


def test_simulate_payment_requires_linked_distributor(seeded):
    s, ctx = seeded
    with pytest.raises(NotFound):
        demo_service.simulate_payment(s, ctx.ramesh.id, "Agarwal Dairy")


def test_customer_payment_chimes_on_merchants_soundbox(seeded):
    s, ctx = seeded
    demo_service.simulate_customer_payment(s, ctx.ramesh.id, 2_500)
    assert "2,500 prapt hue" in message_service.list_events(s, ctx.ramesh.id)[-1].text


def test_demo_reset_restores_seed(seeded):
    s, ctx = seeded
    demo_service.simulate_payment(s, ctx.ramesh.id)
    demo_service.reset(s)
    ramesh = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2308")).one()
    assert ramesh.status == "open"
    assert message_service.list_events(s, 3) == []


# ---- issue invoice
LINES = [{"description": "Tea 250g", "hsn": "0902", "qty": 100, "rate": 120.0, "gst_rate": 5}]


def test_issue_invoice_lands_confirmed_in_retailer_ledger(seeded):
    s, ctx = seeded
    n = DbNotifier(s)
    inv = distributor_service.issue_invoice(s, n, ctx.vikas.id, ctx.ramesh.id, LINES, TODAY)
    assert inv.confirmed and inv.merchant_id == ctx.ramesh.id and inv.grand_total == 12_600
    assert inv.source == "distributor_issued"
    msg = s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id)).all()[-1]
    assert inv.invoice_no in msg.text and "12,600" in msg.text


def test_issue_invoice_tax_split_intra_state(seeded):
    s, ctx = seeded
    inv = distributor_service.issue_invoice(s, DbNotifier(s), ctx.vikas.id, ctx.ramesh.id, LINES, TODAY)
    schema = invoice_loader.to_schema(s, inv)
    assert schema.line_items[0].cgst == 300 and schema.line_items[0].igst == 0


def test_issued_invoice_numbers_increment(seeded):
    s, ctx = seeded
    a = distributor_service.issue_invoice(s, DbNotifier(s), ctx.vikas.id, ctx.ramesh.id, LINES, TODAY)
    b = distributor_service.issue_invoice(s, DbNotifier(s), ctx.vikas.id, ctx.ramesh.id, LINES, TODAY)
    assert a.invoice_no != b.invoice_no


def test_issue_invoice_validations(seeded):
    s, ctx = seeded
    with pytest.raises(Invalid):
        distributor_service.issue_invoice(s, DbNotifier(s), ctx.vikas.id, ctx.ramesh.id, [], TODAY)
    with pytest.raises(NotFound):
        distributor_service.issue_invoice(s, DbNotifier(s), ctx.neha.id, ctx.ramesh.id, LINES, TODAY)


# ---- reminders
def fake_drafter(**kw):
    return f"{kw['tone']}|{kw['retailer_name']}|{kw['amount']:.0f}"


def test_reminders_only_for_overdue_with_tone(seeded):
    s, ctx = seeded
    drafts = distributor_service.draft_reminders(s, ctx.vikas.id, TODAY, fake_drafter)
    assert drafts and all(d.amount > 0 and d.days_overdue > 0 for d in drafts)
    assert any(d.tone == "final" for d in drafts)
    assert ctx.ramesh.id not in {d.retailer_id for d in drafts}  # Ramesh isn't overdue


def test_reminders_filtered_by_retailer(seeded):
    s, ctx = seeded
    first = distributor_service.draft_reminders(s, ctx.vikas.id, TODAY, fake_drafter)[0]
    only = distributor_service.draft_reminders(s, ctx.vikas.id, TODAY, fake_drafter, [first.retailer_id])
    assert [d.retailer_id for d in only] == [first.retailer_id]


def test_send_reminders_notifies_each_retailer(seeded):
    s, ctx = seeded
    drafts = distributor_service.draft_reminders(s, ctx.vikas.id, TODAY, fake_drafter)[:3]
    assert distributor_service.send_reminders(DbNotifier(s), drafts) == 3
    for d in drafts:
        assert s.exec(select(Message).where(Message.merchant_id == d.retailer_id)).first().text == d.text


# ---- credit notes
def test_request_credit_note_creates_and_notifies(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    note = credit_note_service.request_credit_note(s, DbNotifier(s), ctx.ramesh.id, inv.id, 1_000, TODAY)
    assert note.status == "expected" and note.amount == 1_000
    assert "credit note" in s.exec(select(Message).where(Message.merchant_id == ctx.vikas.id)).all()[-1].text


def test_request_credit_note_is_idempotent_per_invoice(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    a = credit_note_service.request_credit_note(s, DbNotifier(s), ctx.ramesh.id, inv.id, 1_000, TODAY)
    b = credit_note_service.request_credit_note(s, DbNotifier(s), ctx.ramesh.id, inv.id, 1_000, TODAY)
    assert a.id == b.id
    assert len(s.exec(select(CreditNote).where(CreditNote.against_invoice_id == inv.id)).all()) == 1


def test_request_credit_note_validations(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    with pytest.raises(Invalid):
        credit_note_service.request_credit_note(s, DbNotifier(s), ctx.ramesh.id, inv.id, 0, TODAY)
    with pytest.raises(NotFound):
        credit_note_service.request_credit_note(s, DbNotifier(s), ctx.neha.id, inv.id, 100, TODAY)


# ---- loaders / dates
def test_invoice_loader_roundtrip_validates_clean(seeded):
    s, ctx = seeded
    from app.engine.validate import validate_invoice
    row = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    schema = invoice_loader.to_schema(s, row)
    assert schema.supplier_name == "Sharma Traders" and schema.grand_total == 42_300
    assert [i.code for i in validate_invoice(schema)] == []


def test_previous_invoices_excludes_given_id(seeded):
    s, ctx = seeded
    row = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    assert all(p.invoice_no != "ST-2302" for p in invoice_loader.previous_invoices(s, ctx.ramesh.id, row.id))


def test_payment_dates_from_both_sides(seeded):
    s, ctx = seeded
    ramesh_inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2291")).one()
    assert payment_dates.last_payment_dates(s, [ramesh_inv.id])[ramesh_inv.id] == date(2026, 10, 12)
    assert payment_dates.last_payment_dates(s, []) == {}


def test_reminders_are_drafted_in_parallel_but_returned_in_order(seeded):
    import threading
    import time
    s, ctx = seeded
    seen = set()

    def slow(**kw):
        seen.add(threading.get_ident())
        time.sleep(0.05)
        return kw["retailer_name"]
    start = time.perf_counter()
    drafts = distributor_service.draft_reminders(s, ctx.vikas.id, TODAY, slow)
    elapsed = time.perf_counter() - start
    assert len(seen) > 1 and elapsed < 0.05 * len(drafts) * 0.6  # side by side, not one after another
    rows = [r for r in distributor_service.receivables(s, ctx.vikas.id, TODAY) if r.overdue_amount > 0]
    assert [d.retailer_name for d in drafts] == [r.name for r in rows]
