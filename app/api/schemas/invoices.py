from datetime import date
from typing import Any

from pydantic import BaseModel

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


class IngestOut(BaseModel):
    invoice_id: int
    invoice: Invoice
    issues: list[IssueOut]
    field_confidence: dict[str, float]
    low_confidence_fields: list[str]
    duplicate: DuplicateOut | None
    image_url: str | None


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
