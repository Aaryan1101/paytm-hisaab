from datetime import datetime

from pydantic import BaseModel, Field


class DraftIn(BaseModel):
    merchant_id: int
    supplier_id: int
    amount: float = Field(gt=0)
    source: str = "bank"


class DraftOut(BaseModel):
    id: int
    supplier_id: int
    amount: float
    source: str
    status: str
    upi_link: str | None


class ConfirmPaymentIn(BaseModel):
    merchant_id: int


class PaymentRecordOut(BaseModel):
    id: int
    amount: float
    mode: str
    paid_at: datetime
    confirmed: bool
    supplier_id: int | None


class CashIn(BaseModel):
    merchant_id: int
    supplier_id: int
    amount: float = Field(gt=0)


class ConfirmPayeeIn(BaseModel):
    supplier_id: int
