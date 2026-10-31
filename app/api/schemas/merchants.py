from datetime import date, datetime

from pydantic import BaseModel


class MerchantOut(BaseModel):
    id: int
    name: str
    role: str
    gst_scheme: str
    language: str


class DueItemOut(BaseModel):
    supplier_id: int
    supplier_name: str
    amount: float
    next_due: date
    invoice_nos: list[str]


class DuesOut(BaseModel):
    period: str
    total: float
    items: list[DueItemOut]


class SupplierSummaryOut(BaseModel):
    id: int
    name: str
    balance_due: float
    next_due: date | None
    risk: str  # low | medium | high
    gstin_status: str


class LedgerEntryOut(BaseModel):
    day: date
    kind: str
    ref: str
    amount: float
    balance: float
    status: str | None


class AlertOut(BaseModel):
    id: int
    type: str
    severity: str
    message_en: str
    message_hi: str
    invoice_id: int | None
    supplier_id: int | None
    payment_id: int | None
    status: str


class LedgerOut(BaseModel):
    supplier_id: int
    supplier_name: str
    balance_due: float
    entries: list[LedgerEntryOut]
    open_issues: list[AlertOut]


class ImsEntryOut(BaseModel):
    id: int
    supplier_name: str
    invoice_no: str
    invoice_date: date
    taxable: float
    tax: float
    action: str | None
    reason_en: str | None
    reason_hi: str | None
    itc_risk: bool
    approved: bool


class ImsMissingOut(BaseModel):
    invoice_id: int
    invoice_no: str
    reason_en: str
    reason_hi: str


class ImsOut(BaseModel):
    month: str
    counts: dict[str, int]
    entries: list[ImsEntryOut]
    missing_from_ims: list[ImsMissingOut]


class OverrideIn(BaseModel):
    action: str


class ForecastDayOut(BaseModel):
    day: date
    inflow: float
    outflow: float
    balance: float
    low: float
    high: float


class ForecastOut(BaseModel):
    buffer: float
    first_below_date: date | None
    shortfall_date: date | None
    shortfall_amount: float
    days: list[ForecastDayOut]


class ReasonOut(BaseModel):
    factor: str
    positive: bool
    text_en: str
    text_hi: str


class ScoreOut(BaseModel):
    score: int
    factors: dict[str, float]
    reasons: list[ReasonOut]


class ConsentIn(BaseModel):
    scope: list[str]


class ConsentOut(BaseModel):
    id: int
    scope: list[str]
    granted_at: datetime
    expires_at: datetime


class CreditOfferOut(BaseModel):
    eligible: bool
    reason: str
    offer_id: int | None = None
    limit: float = 0
    rate_apr_min: float = 0
    rate_apr_max: float = 0
    tenure_days: int = 0
    reasons: list[str] = []
    illustrative: bool = True


class HomeOut(BaseModel):
    merchant: MerchantOut
    owe_this_week: float
    cash_balance: float
    suppliers_due_this_week: int
    alert_count: int
    score: int
    shortfall_date: date | None
    shortfall_amount: float
    forecast: list[ForecastDayOut]


class PendingMatchOut(BaseModel):
    match_id: int
    invoice_id: int
    invoice_no: str
    counterparty: str
    amount: float
    method: str
    confidence: float
    when: datetime


class CashBalanceIn(BaseModel):
    amount: float


class CashBalanceOut(BaseModel):
    cash_balance: float


class ExtractionAccuracyOut(BaseModel):
    accuracy: float | None
    bills: int
    fields: int
