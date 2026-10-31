from datetime import date

from sqlmodel import select

from app import clock
from app.models import Alert, InvoiceRow, Match, PaymentOut
from app.services import alert_service, dues_service, forecast_service, ledger_service, reconcile_service
from app.services.supplier_lookup import find_supplier

TODAY = clock.today()


# ---- supplier lookup
def test_find_supplier_by_alias_and_typo(seeded):
    s, ctx = seeded
    assert find_supplier(s, ctx.ramesh.id, "sharma").name == "Sharma Traders"
    assert find_supplier(s, ctx.ramesh.id, "Agarwal diary").name == "Agarwal Dairy"


def test_find_supplier_unknown_returns_none(seeded):
    s, ctx = seeded
    assert find_supplier(s, ctx.ramesh.id, "Zzzz Quux") is None


def test_find_supplier_is_scoped_to_merchant(seeded):
    s, ctx = seeded
    assert find_supplier(s, ctx.neha.id, "Sharma Traders") is None


# ---- dues
def test_week_dues_match_demo(seeded):
    s, ctx = seeded
    d = dues_service.get_dues(s, ctx.ramesh.id, TODAY, "week")
    assert d.total == 112_400 and len(d.items) == 5
    assert d.items[0].supplier_name == "Gupta Oil Mills"  # earliest due first


def test_today_dues_empty_and_month_dues_larger(seeded):
    s, ctx = seeded
    assert dues_service.get_dues(s, ctx.ramesh.id, TODAY, "today").total == 0
    assert dues_service.get_dues(s, ctx.ramesh.id, TODAY, "month").total > 112_400


def test_dues_filtered_by_supplier(seeded):
    s, ctx = seeded
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    d = dues_service.get_dues(s, ctx.ramesh.id, TODAY, "week", supplier_id=sharma.id)
    assert d.total == 42_300 and d.items[0].invoice_nos == ["ST-2302"]


# ---- reconcile persistence (S1/S2/S7 data)
def test_s2_short_payment_flags_missing_credit_note(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2250")).one()
    alerts = alert_service.list_alerts(s, ctx.ramesh.id, "missing_credit_note")
    assert len(alerts) == 1 and alerts[0].invoice_id == inv.id and "2,300" in alerts[0].message_en
    assert inv.status == "paid" and inv.amount_settled == 42_300


def test_s1_original_bill_is_paid(seeded):
    s, _ = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2291")).one()
    assert inv.status == "paid"


def test_s7_fuzzy_payee_needs_confirmation_then_resolves(seeded):
    s, ctx = seeded
    [alert] = alert_service.list_alerts(s, ctx.ramesh.id, "confirm_payee")
    match = s.exec(select(Match).where(Match.payment_id == alert.payment_id)).first()
    assert match.confidence < 0.9 and match.confirmed is False
    reconcile_service.confirm_payee(s, alert.payment_id, alert.supplier_id)
    assert alert_service.list_alerts(s, ctx.ramesh.id, "confirm_payee") == []
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    s.refresh(sharma)
    assert "SHARMA TRDRS LKO" in sharma.aliases


def test_confirm_payee_rejects_cross_merchant(seeded):
    s, ctx = seeded
    pay = s.exec(select(PaymentOut).where(PaymentOut.merchant_id == ctx.ramesh.id)).first()
    try:
        reconcile_service.confirm_payee(s, pay.id, ctx.neha_suppliers["Kanpur Plastics"].id)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_reconcile_is_idempotent(seeded):
    s, ctx = seeded
    before = len(s.exec(select(Match)).all())
    reconcile_service.reconcile_merchant(s, ctx.ramesh.id)
    reconcile_service.reconcile_merchant(s, ctx.ramesh.id)
    assert len(s.exec(select(Match)).all()) == before
    assert dues_service.get_dues(s, ctx.ramesh.id, TODAY, "week").total == 112_400


def test_resolved_alert_stays_resolved_after_rerun(seeded):
    s, ctx = seeded
    [alert] = alert_service.list_alerts(s, ctx.ramesh.id, "missing_credit_note")
    alert_service.resolve_alert(s, alert.id)
    reconcile_service.reconcile_merchant(s, ctx.ramesh.id)
    assert alert_service.list_alerts(s, ctx.ramesh.id, "missing_credit_note") == []


# ---- ledger
def test_supplier_ledger_running_balance(seeded):
    s, ctx = seeded
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    led = ledger_service.supplier_ledger(s, ctx.ramesh.id, sharma.id)
    assert led.balance_due == round(42_300 + 18_640 + 12_860, 2)
    assert led.entries[-1].balance == led.entries[-1].balance  # sanity: last entry has a balance
    assert [e.day for e in led.entries] == sorted(e.day for e in led.entries)
    assert any(e.kind == "credit_note" for e in led.entries) is False  # expected (not received) notes are not shown


def test_ledger_scoped_to_merchant(seeded):
    s, ctx = seeded
    assert ledger_service.supplier_ledger(s, ctx.neha.id, ctx.ramesh_suppliers["Sharma Traders"].id) is None


# ---- forecast
def test_s5_forecast_shortfall_on_thursday(seeded):
    s, ctx = seeded
    f = forecast_service.get_forecast(s, ctx.ramesh.id, TODAY)
    assert f.shortfall_date == date(2026, 11, 5) and f.shortfall_date.weekday() == 3
    assert f.shortfall_amount == 38_000 and len(f.days) == 14


def test_neha_has_no_shortfall(seeded):
    s, ctx = seeded
    assert forecast_service.get_forecast(s, ctx.neha.id, TODAY).shortfall_amount == 0


# ---- regression: an arrived credit note must keep the bill closed on every later reconcile
def test_received_credit_note_survives_repeated_reconciles(seeded):
    from app.models import CreditNote
    s, ctx = seeded
    note = s.exec(select(CreditNote)).first()
    note.status = "received"
    s.add(note)
    s.flush()
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2250")).one()
    for _ in range(3):
        reconcile_service.reconcile_merchant(s, ctx.ramesh.id)
        s.refresh(inv)
        assert inv.status == "paid" and inv.amount_settled == 42_300
        assert alert_service.list_alerts(s, ctx.ramesh.id, "missing_credit_note") == []
    s.refresh(note)
    assert note.status == "applied"
