from datetime import date, datetime

from pydantic import BaseModel, Field


class ReceivableOut(BaseModel):
    retailer_id: int
    name: str
    outstanding: float
    overdue_amount: float
    days_overdue: int
    reliability: float
    suggested_limit: float
    reason_en: str
    reason_hi: str


class SettlementOut(BaseModel):
    collection_id: int
    received_at: datetime
    payer_name: str
    gross: float
    mdr: float
    net: float
    matched: list[dict]
    status: str  # matched | unmatched


class InvoiceLineIn(BaseModel):
    description: str
    hsn: str | None = None
    qty: float = Field(gt=0)
    rate: float = Field(gt=0)
    gst_rate: float = 5


class IssueInvoiceIn(BaseModel):
    retailer_id: int
    lines: list[InvoiceLineIn]
    credit_days: int = 14


class IssuedInvoiceOut(BaseModel):
    invoice_id: int
    invoice_no: str
    grand_total: float
    due_date: date | None


class RemindersIn(BaseModel):
    retailer_ids: list[int] | None = None
    language: str = "hi"
    send: bool = False


class ReminderOut(BaseModel):
    retailer_id: int
    retailer_name: str
    amount: float
    days_overdue: int
    tone: str
    text: str


class RemindersOut(BaseModel):
    sent: bool
    reminders: list[ReminderOut]
