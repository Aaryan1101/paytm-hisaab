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


class MatchedInvoiceOut(BaseModel):
    invoice_no: str
    amount: float
    match_id: int
    confidence: float
    confirmed: bool  # false = "Confirm?" chip


class SettlementOut(BaseModel):
    collection_id: int
    received_at: datetime
    payer_id: int
    payer_name: str
    gross: float
    mdr: float
    net: float
    matched: list[MatchedInvoiceOut]
    status: str  # matched | unmatched


class RetailerInvoiceOut(BaseModel):
    invoice_id: int
    invoice_no: str
    invoice_date: date
    due_date: date | None
    grand_total: float
    amount_settled: float
    status: str
    source: str


class OpenQueryOut(BaseModel):
    query_id: int
    retailer_id: int
    retailer_name: str
    invoice_id: int
    invoice_no: str
    text: str
    created_at: datetime


class RetailerDetailOut(ReceivableOut):
    invoices: list[RetailerInvoiceOut]
    receipts: list[SettlementOut]
    open_queries: list[OpenQueryOut]


class CreditNoteIssueIn(BaseModel):
    retailer_id: int
    invoice_id: int
    amount: float = Field(gt=0)


class CreditNoteIssuedOut(BaseModel):
    credit_note_id: int
    invoice_id: int | None
    amount: float
    status: str


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
    texts: dict[int, str] | None = None  # retailer_id -> edited message; replaces the AI draft for that retailer


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
