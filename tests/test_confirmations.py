from datetime import timedelta

import pytest
from sqlmodel import select

from app import clock
from app.ai.graph.checkpointing import memory_checkpointer, postgres_checkpointer
from app.ai.graph.confirmations import (ALREADY_DONE, BAD_CHOICE, EXPIRED, NOT_FOUND, NOT_YOURS, Confirmations,
                                        buttons_for)
from app.ai.graph.pending import PendingAction, for_bill, YES_NO_CASH, YES_NO_PAY
from app.channels.db_notifier import DbNotifier
from app.config import settings
from app.models import InvoiceRow, Message, PaymentDraft, PaymentOut
from app.services import payment_service


def cash_pending(s, ctx, amount=3000):
    pay = payment_service.log_cash_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Agarwal Dairy"].id, amount, clock.now())
    return pay, PendingAction("cash", pay.id, YES_NO_CASH)


def test_start_pauses_and_nothing_happens_until_resumed(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    pay, pending = cash_pending(s, ctx)
    conf.start(ctx.ramesh.id, pending)
    assert s.get(PaymentOut, pay.id).confirmed is False


def test_resume_yes_runs_the_business_action(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    pay, pending = cash_pending(s, ctx)
    thread = conf.start(ctx.ramesh.id, pending)
    reply = conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ok")
    assert "pakka kar diya" in reply and s.get(PaymentOut, pay.id).confirmed is True


def test_resume_no_cancels(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    pay, pending = cash_pending(s, ctx)
    thread = conf.start(ctx.ramesh.id, pending)
    assert "hata di" in conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "no")
    assert s.get(PaymentOut, pay.id) is None


def test_second_tap_does_nothing(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    d = payment_service.draft_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Gupta Oil Mills"].id, 19_800, "bank")
    thread = conf.start(ctx.ramesh.id, PendingAction("pay", d.id, YES_NO_PAY))
    first = conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ok")
    balance_after_first = ctx.ramesh.opening_balance
    assert "ho gaya" in first
    assert conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ok") == ALREADY_DONE
    assert len(s.exec(select(PaymentOut).where(PaymentOut.mode == "upi", PaymentOut.amount == 19_800)).all()) >= 1
    s.refresh(ctx.ramesh)
    assert ctx.ramesh.opening_balance == balance_after_first  # not debited twice


def test_only_the_owner_can_answer(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    pay, pending = cash_pending(s, ctx)
    thread = conf.start(ctx.ramesh.id, pending)
    assert conf.resume(s, DbNotifier(s), ctx.neha.id, thread, "ok") == NOT_YOURS
    assert s.get(PaymentOut, pay.id).confirmed is False


def test_unknown_thread_and_bad_choice(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    assert conf.resume(s, DbNotifier(s), ctx.ramesh.id, "c-nope", "ok") == NOT_FOUND
    pay, pending = cash_pending(s, ctx)
    thread = conf.start(ctx.ramesh.id, pending)
    assert conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "explode") == BAD_CHOICE
    assert s.get(PaymentOut, pay.id).confirmed is False  # a bad choice leaves it pending


def test_stale_requests_expire(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer(), max_age=timedelta(seconds=-1))
    pay, pending = cash_pending(s, ctx)
    thread = conf.start(ctx.ramesh.id, pending)
    assert conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ok") == EXPIRED
    assert s.get(PaymentOut, pay.id).confirmed is False


def test_business_errors_become_polite_replies_not_crashes(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    d = payment_service.draft_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Gupta Oil Mills"].id, 100, "bank")
    payment_service.cancel_draft(s, ctx.ramesh.id, d.id)  # draft no longer confirmable
    thread = conf.start(ctx.ramesh.id, PendingAction("pay", d.id, YES_NO_PAY))
    assert conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ok").startswith("Nahi ho paya")


def test_threads_are_independent(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    a, pa = cash_pending(s, ctx, 100)
    b, pb = cash_pending(s, ctx, 200)
    ta, tb = conf.start(ctx.ramesh.id, pa), conf.start(ctx.ramesh.id, pb)
    conf.resume(s, DbNotifier(s), ctx.ramesh.id, ta, "ok")
    assert s.get(PaymentOut, a.id).confirmed and not s.get(PaymentOut, b.id).confirmed
    assert ta != tb


def test_bill_decisions_use_the_same_mechanism(seeded):
    s, ctx = seeded
    conf = Confirmations(memory_checkpointer())
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    thread = conf.start(ctx.ramesh.id, for_bill(inv.id, "Sharma Traders", is_duplicate=True))
    assert "Supplier ko message bhej diya" in conf.resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ask")
    assert "sawaal poocha hai" in s.exec(select(Message).where(Message.merchant_id == ctx.vikas.id)).all()[-1].text


def test_button_ids_and_titles():
    p = for_bill(5, "Sharma Traders", True)
    buttons = buttons_for("c-abc", p.options)
    assert [b.id for b in buttons] == ["g:c-abc:ignore", "g:c-abc:new", "g:c-abc:ask"] and buttons[2].title == "Sharma se poochho"
    assert [o.choice for o in for_bill(5, "X", False).options] == ["ok", "no"]


def test_pending_decision_survives_a_restart_in_postgres(seeded):
    s, ctx = seeded
    try:
        first = postgres_checkpointer(settings.database_url)
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not available: {e}")
    pay, pending = cash_pending(s, ctx)
    thread = Confirmations(first).start(ctx.ramesh.id, pending)
    first.conn.close()
    second = postgres_checkpointer(settings.database_url)  # a "restarted" server
    reply = Confirmations(second).resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ok")
    assert "pakka kar diya" in reply and s.get(PaymentOut, pay.id).confirmed
    assert Confirmations(second).resume(s, DbNotifier(s), ctx.ramesh.id, thread, "ok") == ALREADY_DONE
    second.delete_thread(thread)
    second.conn.close()
