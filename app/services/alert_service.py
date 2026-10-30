"""Creating, listing and resolving alerts."""
from sqlmodel import Session, select

from app.models import Alert

SYSTEM_TYPES = ("missing_credit_note", "confirm_payee")


def list_alerts(session: Session, merchant_id: int, type: str | None = None, status: str = "open") -> list[Alert]:
    q = select(Alert).where(Alert.merchant_id == merchant_id, Alert.status == status)
    if type:
        q = q.where(Alert.type == type)
    return list(session.exec(q.order_by(Alert.id)).all())


def add_alert(session: Session, merchant_id: int, type: str, severity: str, message_en: str, message_hi: str,
              invoice_id: int | None = None, supplier_id: int | None = None, payment_id: int | None = None) -> Alert:
    alert = Alert(merchant_id=merchant_id, type=type, severity=severity, message_en=message_en, message_hi=message_hi,
                  invoice_id=invoice_id, supplier_id=supplier_id, payment_id=payment_id)
    session.add(alert)
    session.flush()
    return alert


def replace_system_alerts(session: Session, merchant_id: int, fresh: list[Alert],
                          types: tuple[str, ...] = SYSTEM_TYPES) -> None:
    """Swap one producer's open alerts (by type) for a fresh set, leaving resolved ones resolved."""
    for old in session.exec(select(Alert).where(Alert.merchant_id == merchant_id, Alert.status == "open",
                                                Alert.type.in_(types))).all():
        session.delete(old)
    resolved = {(a.type, a.invoice_id, a.payment_id) for a in session.exec(
        select(Alert).where(Alert.merchant_id == merchant_id, Alert.status == "resolved", Alert.type.in_(types))).all()}
    for a in fresh:
        if (a.type, a.invoice_id, a.payment_id) not in resolved:
            session.add(a)
    session.flush()


def resolve_alert(session: Session, alert_id: int) -> Alert | None:
    alert = session.get(Alert, alert_id)
    if alert:
        alert.status = "resolved"
        session.add(alert)
        session.flush()
    return alert
