from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.models.schemas import Invoice


class IssueOut(BaseModel):
    code: str
    severity: str
    message_en: str
    message_hi: str
    field: str | None = None
    line_index: int | None = None


class DuplicateOut(BaseModel):
    invoice_id: int
    invoice_no: str
    invoice_date: date
    paid_on: date | None
    amount: float


class IngestOut(BaseModel):
    invoice_id: int
    invoice: Invoice
    issues: list[IssueOut]
    field_confidence: dict[str, float]
    low_confidence_fields: list[str]
    duplicate: DuplicateOut | None
    image_url: str | None
    supplier_name: str  # as the ledger knows them


class ConfirmIn(BaseModel):
    corrections: dict[str, Any] | None = None


class InvoiceStateOut(BaseModel):
    id: int
    invoice_no: str
    status: str
    confirmed: bool
    grand_total: float
    amount_settled: float


class QueryOut(BaseModel):
    id: int
    status: str
    invoice_id: int
    answer: str | None = None


class AnswerIn(BaseModel):
    answer: str


class CreditNoteRequestIn(BaseModel):
    amount: float = Field(gt=0)


class CreditNoteOut(BaseModel):
    id: int
    invoice_id: int | None
    amount: float
    status: str  # expected (requested, not yet issued) | received | applied
