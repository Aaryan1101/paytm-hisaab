"""Loads a merchant's cash data and runs the forecast engine."""
from datetime import date, timedelta

from sqlmodel import Session, select

from app.engine import forecast as engine
from app.models import CollectionIn, Merchant, PaymentOut
from app.services import dues_service

EXPENSE_WINDOW_DAYS = 56


def forecast_inputs(session: Session, merchant_id: int, today: date) -> dict:
    window_start = today - timedelta(days=engine.HISTORY_WEEKS * 7)
    daily: dict[date, float] = {}
    for c in session.exec(select(CollectionIn).where(CollectionIn.merchant_id == merchant_id,
                                                     CollectionIn.payer_merchant_id == None,  # noqa: E711
                                                     CollectionIn.received_at >= window_start)).all():
        daily[c.received_at.date()] = daily.get(c.received_at.date(), 0.0) + c.net_amount
    expenses = sum(p.amount for p in session.exec(select(PaymentOut).where(
        PaymentOut.merchant_id == merchant_id, PaymentOut.category == "expense",
        PaymentOut.paid_at >= today - timedelta(days=EXPENSE_WINDOW_DAYS))).all())
    dues = [(i.due_date, dues_service.remaining(i)) for i in dues_service.open_invoices(session, merchant_id) if i.due_date]
    return {"daily_collections": daily, "dues": dues, "other_daily_spend": expenses / EXPENSE_WINDOW_DAYS}


def get_forecast(session: Session, merchant_id: int, today: date, days: int = 14) -> engine.Forecast:
    merchant = session.get(Merchant, merchant_id)
    return engine.build_forecast(today, merchant.opening_balance, days=days, **forecast_inputs(session, merchant_id, today))
