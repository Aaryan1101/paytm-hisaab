"""Proactive messages: "bill due tomorrow" reminders (with a Soundbox announcement) and the weekly payables digest.

Every send claims a unique (merchant, kind, key) row first, so running a job twice, or from two places, never messages
anyone twice.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.ai import templates
from app.ai.money_format import inr, spoken
from app.channels.base import Notifier
from app.models import Merchant, NotificationLog
from app.services import dues_service, message_service
from app.services.dues_service import remaining

DUE_TOMORROW, WEEKLY_DIGEST = "due_tomorrow", "weekly_digest"


@dataclass(frozen=True)
class Sent:
    merchant_id: int
    kind: str
    text: str


def _claim(session: Session, merchant_id: int, kind: str, key: str) -> bool:
    """Record that this message is being sent. False if it was already sent."""
    if session.exec(select(NotificationLog).where(NotificationLog.merchant_id == merchant_id, NotificationLog.kind == kind,
                                                  NotificationLog.key == key)).first():
        return False
    try:
        with session.begin_nested():
            session.add(NotificationLog(merchant_id=merchant_id, kind=kind, key=key))
    except IntegrityError:  # lost a race with another worker
        return False
    return True


def _payers(session: Session, merchant_ids: list[int] | None) -> list[Merchant]:
    q = select(Merchant).where(Merchant.role != "distributor").order_by(Merchant.id)
    return [m for m in session.exec(q).all() if merchant_ids is None or m.id in merchant_ids]


def send_due_tomorrow(session: Session, notifier: Notifier, today: date, merchant_ids: list[int] | None = None) -> list[Sent]:
    """For each supplier with an unpaid bill due tomorrow: a WhatsApp message and a Soundbox announcement."""
    due_day, sent = today + timedelta(days=1), []
    from app.models import Supplier
    for m in _payers(session, merchant_ids):
        names = {s.id: s.name for s in session.exec(select(Supplier).where(Supplier.merchant_id == m.id)).all()}
        groups: dict[int, list] = {}
        for inv in dues_service.open_invoices(session, m.id):
            if inv.due_date == due_day:
                groups.setdefault(inv.supplier_id, []).append(inv)
        for sid, invs in sorted(groups.items()):
            if not _claim(session, m.id, DUE_TOMORROW, f"{sid}:{due_day.isoformat()}"):
                continue
            total, name = round(sum(remaining(i) for i in invs), 2), names[sid]
            nos = ", ".join(i.invoice_no for i in invs)
            hindi = m.language != "en"
            text = (f"{name} ka bill kal due hai, {inr(total)} ({nos})." if hindi else f"{name}: a bill of {inr(total)} is due tomorrow ({nos}).")
            heard = (f"{name} ka bill kal due hai, {spoken(total)} rupaye." if hindi else f"{name}'s bill of {spoken(total)} rupees is due tomorrow.")
            notifier.send(m.id, text)
            message_service.push_event(session, m.id, heard)
            sent.append(Sent(m.id, DUE_TOMORROW, text))
    return sent


def send_weekly_digest(session: Session, notifier: Notifier, today: date, merchant_ids: list[int] | None = None) -> list[Sent]:
    """What each merchant owes in the next 7 days, once per ISO week. Skipped when nothing is due."""
    iso = today.isocalendar()
    key, sent = f"{iso.year}-W{iso.week:02d}", []
    for m in _payers(session, merchant_ids):
        dues = dues_service.get_dues(session, m.id, today, "week")
        if not dues.items or not _claim(session, m.id, WEEKLY_DIGEST, key):
            continue
        result = {"period": "week", "total": dues.total, "total_display": inr(dues.total), "count": len(dues.items),
                  "items": [{"supplier": i.supplier_name, "amount": i.amount, "amount_display": inr(i.amount),
                             "due_date": i.next_due.isoformat(), "invoices": i.invoice_nos} for i in dues.items]}
        text = templates.render("get_dues", result, "en" if m.language == "en" else "hi", "whatsapp")
        notifier.send(m.id, text)
        sent.append(Sent(m.id, WEEKLY_DIGEST, text))
    return sent
