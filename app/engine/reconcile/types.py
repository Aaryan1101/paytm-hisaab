"""Plain data carried in and out of the reconciliation engine (no DB, no framework)."""
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class SupplierRef:
    id: int
    name: str
    aliases: tuple[str, ...] = ()
    payee_vpa: str | None = None


@dataclass(frozen=True)
class InvoiceIn:
    id: int
    supplier_id: int
    invoice_no: str
    invoice_date: date
    total: float
    already_applied: float = 0.0


@dataclass(frozen=True)
class PaymentIn:
    id: int
    amount: float
    paid_at: date
    supplier_id: int | None = None
    payee_name: str | None = None
    payee_vpa: str | None = None
    remark: str | None = None
    already_applied: float = 0.0


@dataclass(frozen=True)
class CreditNoteIn:
    id: int
    supplier_id: int
    amount: float
    status: str  # expected | received | applied
    against_invoice_id: int | None = None


@dataclass(frozen=True)
class MatchOut:
    invoice_id: int
    payment_id: int
    amount: float
    method: str  # reference | exact | many_to_one | partial
    confidence: float


@dataclass(frozen=True)
class CreditApplication:
    credit_note_id: int
    invoice_id: int
    amount: float


@dataclass(frozen=True)
class AlertOut:
    type: str
    severity: str
    supplier_id: int
    invoice_id: int | None
    amount: float
    message_en: str
    message_hi: str
    credit_note_id: int | None = None


@dataclass(frozen=True)
class FuzzySuggestion:
    payment_id: int
    supplier_id: int
    score: float


@dataclass
class ReconcileResult:
    matches: list[MatchOut] = field(default_factory=list)
    credit_applications: list[CreditApplication] = field(default_factory=list)
    alerts: list[AlertOut] = field(default_factory=list)
    fuzzy_suggestions: list[FuzzySuggestion] = field(default_factory=list)
    invoice_status: dict[int, str] = field(default_factory=dict)  # open | part_paid | paid
    unmatched_payment_ids: list[int] = field(default_factory=list)
    unpaid_invoice_ids: list[int] = field(default_factory=list)
