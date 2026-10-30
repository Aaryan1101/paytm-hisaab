from datetime import datetime

import pytest
from sqlmodel import select

from app import clock
from app.models import CollectionIn, CreditOffer, InvoiceRow, Merchant, PaymentDraft, PaymentOut
from app.services import credit_service, dues_service, payment_service, score_service
from app.services.errors import ConsentRequired, Invalid, NotFound

TODAY = clock.today()
NOW = datetime(2026, 10, 31, 12, 0)
SCOPE = ["gst_data", "bank_data"]


# ---- score
def test_ramesh_score_is_lender_grade(seeded):
    s, ctx = seeded
    r = score_service.get_score(s, ctx.ramesh.id, TODAY)
    assert r.result.score >= 600 and len(r.result.reasons) == 3
    assert r.inputs.history_days >= 90 and r.inputs.invoices_total > 20


def test_score_reasons_have_both_languages(seeded):
    s, ctx = seeded
    for reason in score_service.get_score(s, ctx.ramesh.id, TODAY).result.reasons:
        assert reason.text_en and reason.text_hi


# ---- credit
def test_offer_requires_consent(seeded):
    s, ctx = seeded
    with pytest.raises(ConsentRequired):
        credit_service.create_offer(s, ctx.ramesh.id, TODAY, NOW)


def test_consent_with_missing_scope_is_not_enough(seeded):
    s, ctx = seeded
    credit_service.grant_consent(s, ctx.ramesh.id, ["gst_data"], NOW)
    assert credit_service.active_consent(s, ctx.ramesh.id, NOW) is None


def test_expired_consent_not_active(seeded):
    s, ctx = seeded
    credit_service.grant_consent(s, ctx.ramesh.id, SCOPE, datetime(2026, 1, 1))
    assert credit_service.active_consent(s, ctx.ramesh.id, NOW) is None


def test_s5_offer_is_fifty_thousand(seeded):
    s, ctx = seeded
    credit_service.grant_consent(s, ctx.ramesh.id, SCOPE, NOW)
    offer, decision = credit_service.create_offer(s, ctx.ramesh.id, TODAY, NOW)
    assert decision.eligible and offer.limit_amount == 50_000 and len(offer.reasons) == 3


def test_no_offer_without_shortfall(seeded):
    s, ctx = seeded
    credit_service.grant_consent(s, ctx.neha.id, SCOPE, NOW)
    offer, decision = credit_service.create_offer(s, ctx.neha.id, TODAY, NOW)
    assert offer is None and not decision.eligible


def test_preview_needs_no_consent(seeded):
    s, ctx = seeded
    decision, _ = credit_service.preview(s, ctx.ramesh.id, TODAY)
    assert decision.eligible and decision.limit == 50_000


def test_reissuing_offer_replaces_old_one(seeded):
    s, ctx = seeded
    credit_service.grant_consent(s, ctx.ramesh.id, SCOPE, NOW)
    credit_service.create_offer(s, ctx.ramesh.id, TODAY, NOW)
    credit_service.create_offer(s, ctx.ramesh.id, TODAY, NOW)
    assert len(s.exec(select(CreditOffer).where(CreditOffer.merchant_id == ctx.ramesh.id)).all()) == 1


def test_accept_offer_rules(seeded):
    s, ctx = seeded
    credit_service.grant_consent(s, ctx.ramesh.id, SCOPE, NOW)
    offer, _ = credit_service.create_offer(s, ctx.ramesh.id, TODAY, NOW)
    with pytest.raises(NotFound):
        credit_service.accept_offer(s, ctx.neha.id, offer.id)
    assert credit_service.accept_offer(s, ctx.ramesh.id, offer.id).status == "accepted"
    with pytest.raises(Invalid):
        credit_service.accept_offer(s, ctx.ramesh.id, offer.id)


# ---- payments
def test_draft_does_not_move_money(seeded):
    s, ctx = seeded
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    before = ctx.ramesh.opening_balance
    d = payment_service.draft_payment(s, ctx.ramesh.id, sharma.id, 5_000, "bank")
    assert d.status == "drafted" and d.upi_link.startswith("upi://pay?pa=") and "am=5000.00" in d.upi_link
    s.refresh(ctx.ramesh)
    assert ctx.ramesh.opening_balance == before


def test_confirm_bank_payment_reduces_balance_and_reconciles(seeded):
    s, ctx = seeded
    gupta = ctx.ramesh_suppliers["Gupta Oil Mills"]
    before = ctx.ramesh.opening_balance
    d = payment_service.draft_payment(s, ctx.ramesh.id, gupta.id, 19_800, "bank")
    payment_service.confirm_payment(s, ctx.ramesh.id, d.id, NOW)
    s.refresh(ctx.ramesh)
    assert ctx.ramesh.opening_balance == pytest.approx(before - 19_800)
    assert dues_service.get_dues(s, ctx.ramesh.id, TODAY, "week").total == 112_400 - 19_800
    assert s.get(PaymentDraft, d.id).status == "confirmed"


def test_confirm_twice_rejected(seeded):
    s, ctx = seeded
    d = payment_service.draft_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Gupta Oil Mills"].id, 100, "bank")
    payment_service.confirm_payment(s, ctx.ramesh.id, d.id, NOW)
    with pytest.raises(Invalid):
        payment_service.confirm_payment(s, ctx.ramesh.id, d.id, NOW)


def test_payment_to_linked_distributor_creates_receipt(seeded):
    s, ctx = seeded
    n = len(s.exec(select(CollectionIn).where(CollectionIn.merchant_id == ctx.vikas.id)).all())
    d = payment_service.draft_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Sharma Traders"].id, 42_300, "bank")
    payment_service.confirm_payment(s, ctx.ramesh.id, d.id, NOW)
    rows = s.exec(select(CollectionIn).where(CollectionIn.merchant_id == ctx.vikas.id)).all()
    assert len(rows) == n + 1 and rows[-1].mdr_amount == 169.2


def test_draft_validations(seeded):
    s, ctx = seeded
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    with pytest.raises(Invalid):
        payment_service.draft_payment(s, ctx.ramesh.id, sharma.id, 0, "bank")
    with pytest.raises(Invalid):
        payment_service.draft_payment(s, ctx.ramesh.id, sharma.id, 100, "cheque")
    with pytest.raises(NotFound):
        payment_service.draft_payment(s, ctx.ramesh.id, ctx.neha_suppliers["Kanpur Plastics"].id, 100, "bank")


def test_credit_payment_requires_accepted_offer_and_respects_limit(seeded):
    s, ctx = seeded
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    with pytest.raises(Invalid):
        payment_service.draft_payment(s, ctx.ramesh.id, sharma.id, 1_000, "credit")
    credit_service.grant_consent(s, ctx.ramesh.id, SCOPE, NOW)
    offer, _ = credit_service.create_offer(s, ctx.ramesh.id, TODAY, NOW)
    credit_service.accept_offer(s, ctx.ramesh.id, offer.id)
    with pytest.raises(Invalid):
        payment_service.draft_payment(s, ctx.ramesh.id, sharma.id, 60_000, "credit")
    d = payment_service.draft_payment(s, ctx.ramesh.id, sharma.id, 42_300, "credit")
    before = ctx.ramesh.opening_balance
    pay = payment_service.confirm_payment(s, ctx.ramesh.id, d.id, NOW)
    s.refresh(ctx.ramesh)
    assert pay.mode == "credit_line" and ctx.ramesh.opening_balance == before  # loan, not bank money
    assert payment_service.credit_used(s, ctx.ramesh.id) == 42_300
    with pytest.raises(Invalid):
        payment_service.draft_payment(s, ctx.ramesh.id, sharma.id, 10_000, "credit")  # only 7,700 left


def test_cash_entry_needs_confirmation_and_is_ignored_until_then(seeded):
    s, ctx = seeded
    agarwal = ctx.ramesh_suppliers["Agarwal Dairy"]
    pay = payment_service.log_cash_payment(s, ctx.ramesh.id, agarwal.id, 3_000, NOW)
    assert pay.confirmed is False
    assert dues_service.get_dues(s, ctx.ramesh.id, TODAY, "week").total == 112_400
    payment_service.confirm_cash_payment(s, ctx.ramesh.id, pay.id)
    assert dues_service.get_dues(s, ctx.ramesh.id, TODAY, "week").total == 112_400 - 3_000


def test_cancel_cash_entry(seeded):
    s, ctx = seeded
    pay = payment_service.log_cash_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Agarwal Dairy"].id, 3_000, NOW)
    payment_service.cancel_cash_payment(s, ctx.ramesh.id, pay.id)
    assert s.get(PaymentOut, pay.id) is None
    with pytest.raises(NotFound):
        payment_service.cancel_cash_payment(s, ctx.ramesh.id, pay.id)
