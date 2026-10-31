import asyncio
from datetime import date, datetime

from sqlmodel import select

from app.channels.db_notifier import DbNotifier
from app.jobs import notifications
from app.jobs.scheduler import run_forever, tick
from app.models import InvoiceRow, Message, NotificationLog
from app.services import message_service, payment_service

NOV3, NOV2 = date(2026, 11, 3), date(2026, 11, 2)   # Nov 3 (Tue): ST-2302 is due tomorrow. Nov 2 (Mon): digest day


def whatsapp_texts(s, merchant_id):
    return [m.text for m in s.exec(select(Message).where(Message.merchant_id == merchant_id, Message.channel == "whatsapp")).all()]


# ---- due tomorrow
def test_due_tomorrow_messages_the_merchant_and_announces_on_the_soundbox(seeded):
    s, ctx = seeded
    sent = notifications.send_due_tomorrow(s, DbNotifier(s), NOV3, [ctx.ramesh.id])
    assert len(sent) == 1 and sent[0].kind == "due_tomorrow"
    assert "Sharma Traders ka bill kal due hai, ₹42,300 (ST-2302)" in whatsapp_texts(s, ctx.ramesh.id)[-1]
    heard = message_service.list_events(s, ctx.ramesh.id)[-1].text
    assert heard == "Sharma Traders ka bill kal due hai, 42 hazaar rupaye."


def test_due_tomorrow_groups_a_suppliers_bills_into_one_message(seeded):
    s, ctx = seeded
    notifications.send_due_tomorrow(s, DbNotifier(s), date(2026, 11, 4), [ctx.ramesh.id])   # Agarwal ₹28,000 and Singh ₹14,200 due Nov 5
    texts = whatsapp_texts(s, ctx.ramesh.id)
    assert len(texts) == 2 and any("Agarwal Dairy" in t and "28,000" in t for t in texts) and any("Singh Rice Co" in t for t in texts)


def test_running_the_job_twice_does_not_repeat_messages(seeded):
    s, ctx = seeded
    first = notifications.send_due_tomorrow(s, DbNotifier(s), NOV3)
    again = notifications.send_due_tomorrow(s, DbNotifier(s), NOV3)
    assert first and again == [] and len(s.exec(select(NotificationLog)).all()) == len(first)


def test_paid_bills_are_not_reminded(seeded):
    s, ctx = seeded
    d = payment_service.draft_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Sharma Traders"].id, 42_300, "bank")
    payment_service.confirm_payment(s, ctx.ramesh.id, d.id, datetime(2026, 11, 2, 10))
    assert notifications.send_due_tomorrow(s, DbNotifier(s), NOV3, [ctx.ramesh.id]) == []


def test_disputed_and_unconfirmed_bills_are_not_reminded(seeded):
    s, ctx = seeded
    inv = s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == "ST-2302")).one()
    inv.confirmed, inv.status = False, "disputed"
    s.add(inv)
    assert notifications.send_due_tomorrow(s, DbNotifier(s), NOV3, [ctx.ramesh.id]) == []


def test_nothing_due_tomorrow_means_no_messages(seeded):
    s, ctx = seeded
    assert notifications.send_due_tomorrow(s, DbNotifier(s), date(2026, 10, 31)) == []


def test_distributors_are_never_sent_payables_reminders(seeded):
    s, ctx = seeded
    notifications.send_due_tomorrow(s, DbNotifier(s), NOV3)
    notifications.send_weekly_digest(s, DbNotifier(s), NOV2)
    assert whatsapp_texts(s, ctx.vikas.id) == []


def test_english_merchants_get_english_text(seeded):
    s, ctx = seeded
    ctx.ramesh.language = "en"
    s.add(ctx.ramesh)
    notifications.send_due_tomorrow(s, DbNotifier(s), NOV3, [ctx.ramesh.id])
    assert "a bill of ₹42,300 is due tomorrow" in whatsapp_texts(s, ctx.ramesh.id)[-1]
    assert "rupees is due tomorrow" in message_service.list_events(s, ctx.ramesh.id)[-1].text


# ---- weekly digest
def test_digest_lists_the_weeks_dues_like_the_chat_answer(seeded):
    s, ctx = seeded
    sent = notifications.send_weekly_digest(s, DbNotifier(s), NOV2, [ctx.ramesh.id])
    text = sent[0].text
    assert sent[0].kind == "weekly_digest" and "• Gupta Oil Mills ₹19,800" in text and "• Sharma Traders ₹42,300" in text
    assert text.startswith("Is hafte 5 suppliers ko ₹1,12,400 dena hai")


def test_digest_is_once_per_week_but_new_weeks_get_a_new_one(seeded):
    s, ctx = seeded
    assert notifications.send_weekly_digest(s, DbNotifier(s), NOV2, [ctx.ramesh.id])
    assert notifications.send_weekly_digest(s, DbNotifier(s), date(2026, 11, 4), [ctx.ramesh.id]) == []   # same ISO week
    assert notifications.send_weekly_digest(s, DbNotifier(s), date(2026, 11, 9), [ctx.ramesh.id])   # next ISO week: a new digest
    keys = sorted(n.key for n in s.exec(select(NotificationLog).where(NotificationLog.kind == "weekly_digest")).all())
    assert keys == ["2026-W45", "2026-W46"]


def test_overdue_bills_still_count_as_owed_in_the_digest(seeded):
    s, ctx = seeded
    text = notifications.send_weekly_digest(s, DbNotifier(s), date(2027, 6, 7), [ctx.ramesh.id])[0].text
    assert "suppliers ko" in text and "Kapoor Beverages" in text   # long overdue, so still listed


def test_digest_skipped_when_nothing_is_owed(seeded):
    s, ctx = seeded
    for inv in s.exec(select(InvoiceRow).where(InvoiceRow.merchant_id == ctx.ramesh.id)).all():
        inv.status = "paid"
        s.add(inv)
    s.flush()
    assert notifications.send_weekly_digest(s, DbNotifier(s), NOV2, [ctx.ramesh.id]) == []


# ---- scheduler tick
def factory(s):
    class Ctx:
        def __enter__(self):
            return s

        def __exit__(self, *a):
            return False
    return lambda: Ctx()


class FakeContainer:
    def __init__(self, s):
        self.s = s

    def notifier(self, session):
        return DbNotifier(session)


def test_tick_waits_for_the_configured_hour(seeded):
    s, _ = seeded
    assert tick(factory(s), FakeContainer(s), datetime(2026, 11, 3, 8, 59), hour=9) == []
    assert tick(factory(s), FakeContainer(s), datetime(2026, 11, 3, 9, 0), hour=9)


def test_tick_sends_the_digest_only_on_mondays(seeded):
    s, _ = seeded
    tuesday = tick(factory(s), FakeContainer(s), datetime(2026, 11, 3, 10), hour=9)
    assert {x.kind for x in tuesday} == {"due_tomorrow"}
    monday = tick(factory(s), FakeContainer(s), datetime(2026, 11, 9, 10), hour=9)
    assert "weekly_digest" in {x.kind for x in monday}


def test_repeated_ticks_do_not_duplicate_anything(seeded):
    s, _ = seeded
    now = datetime(2026, 11, 3, 10)
    first = tick(factory(s), FakeContainer(s), now)
    assert first and tick(factory(s), FakeContainer(s), now) == [] and tick(factory(s), FakeContainer(s), now) == []


# ---- background loop
def test_loop_runs_the_job_repeatedly_and_stops_on_request():
    calls = []

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(run_forever(lambda: calls.append(1), 0.01, stop))
        await asyncio.sleep(0.12)
        stop.set()
        await asyncio.wait_for(task, 1)
    asyncio.run(go())
    assert len(calls) >= 3


def test_a_failing_pass_does_not_kill_the_loop():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database blip")

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(run_forever(flaky, 0.01, stop))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, 1)
    asyncio.run(go())
    assert len(calls) >= 2


# ---- on-demand triggers (for the demo)
def test_demo_endpoints_run_the_jobs_with_a_pretend_date(api):
    c, s, ctx, _ = api
    r = c.post("/demo/run-due-reminders", params={"on": "2026-11-03"}).json()
    assert any("Sharma Traders ka bill kal due hai" in x["text"] for x in r["sent"])
    assert c.post("/demo/run-due-reminders", params={"on": "2026-11-03"}).json() == {"sent": []}
    assert "kal due hai" in c.get(f"/merchants/{ctx.ramesh.id}/events").json()[-1]["text"]
    d = c.post("/demo/run-weekly-digest", params={"on": "2026-11-02"}).json()
    assert d["sent"] and all(x["kind"] == "weekly_digest" for x in d["sent"])


def test_demo_job_endpoints_reject_a_bad_date(api):
    assert api[0].post("/demo/run-due-reminders", params={"on": "tomorrow"}).status_code == 422
