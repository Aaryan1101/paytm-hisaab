"""Writes payment rows, plus the mirror receipt on the distributor side when the payee is on the platform."""
import secrets
from datetime import datetime

from sqlmodel import Session

from app.engine.mdr import mdr_for
from app.models import CollectionIn, PaymentOut, Supplier


def new_utr() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(12))


def record_upi_payment(session: Session, merchant_id: int, supplier: Supplier, amount: float, paid_at: datetime,
                       remark: str | None = None, payee_name: str | None = None, use_vpa: bool = True,
                       mode: str = "upi", utr: str | None = None) -> PaymentOut:
    ref = utr or new_utr()
    pay = PaymentOut(merchant_id=merchant_id, supplier_id=None, amount=amount, paid_at=paid_at, mode=mode, utr=ref,
                     payee_vpa=supplier.payee_vpa if use_vpa else None, payee_name=payee_name or supplier.name,
                     remark=remark)
    session.add(pay)
    if supplier.linked_merchant_id:
        mdr = mdr_for(amount)
        session.add(CollectionIn(merchant_id=supplier.linked_merchant_id, payer_merchant_id=merchant_id, amount=amount,
                                 received_at=paid_at, payer_vpa=f"merchant{merchant_id}@paytm", mdr_amount=mdr,
                                 net_amount=round(amount - mdr, 2), utr=ref))
    session.flush()
    return pay


def record_cash_payment(session: Session, merchant_id: int, supplier: Supplier, amount: float, paid_at: datetime,
                        confirmed: bool = True) -> PaymentOut:
    pay = PaymentOut(merchant_id=merchant_id, supplier_id=supplier.id, amount=amount, paid_at=paid_at, mode="cash",
                     payee_name=supplier.name, confirmed=confirmed)
    session.add(pay)
    session.flush()
    return pay
