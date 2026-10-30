from datetime import date, datetime

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class PaymentOut(SQLModel, table=True):
    __tablename__ = "payments_out"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    supplier_id: int | None = Field(default=None, foreign_key="suppliers.id")
    amount: float
    paid_at: NaiveDatetime
    mode: str  # upi | cash | credit_line
    utr: str | None = None
    payee_vpa: str | None = None
    payee_name: str | None = None
    remark: str | None = None
    confirmed: bool = True  # cash entries from voice start unconfirmed
    category: str = "supplier"  # supplier | expense (rent, wages: never matched to invoices)


class CollectionIn(SQLModel, table=True):
    __tablename__ = "collections_in"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    payer_merchant_id: int | None = Field(default=None, foreign_key="merchants.id")
    amount: float  # gross
    received_at: NaiveDatetime
    payer_vpa: str | None = None
    mdr_amount: float = 0
    net_amount: float
    utr: str | None = None


class Match(SQLModel, table=True):
    __tablename__ = "matches"
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoices.id", index=True)
    payment_id: int | None = Field(default=None, foreign_key="payments_out.id")
    collection_id: int | None = Field(default=None, foreign_key="collections_in.id")
    amount_applied: float
    method: str  # reference | exact | many_to_one | partial | fuzzy | manual
    confidence: float
    confirmed: bool = True


class CreditNote(SQLModel, table=True):
    __tablename__ = "credit_notes"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    supplier_id: int = Field(foreign_key="suppliers.id")
    against_invoice_id: int | None = Field(default=None, foreign_key="invoices.id")
    amount: float
    status: str  # expected | received | applied
    created_on: date | None = None
