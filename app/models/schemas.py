from datetime import date
from typing import Literal

from pydantic import BaseModel


class LineItem(BaseModel):
    description: str
    hsn: str | None = None
    qty: float | None = None
    unit: str | None = None
    rate: float | None = None
    taxable_value: float
    gst_rate: float | None = None  # percent: 0, 5, 18, 40 ...
    cgst: float = 0
    sgst: float = 0
    igst: float = 0


class Invoice(BaseModel):
    supplier_name: str
    supplier_gstin: str | None = None
    buyer_gstin: str | None = None
    invoice_no: str
    invoice_date: date
    due_date: date | None = None
    place_of_supply: str | None = None
    line_items: list[LineItem]
    taxable_total: float
    tax_total: float
    round_off: float = 0
    grand_total: float
    bill_type: Literal["gst_invoice", "kachcha", "credit_note", "debit_note"]
    field_confidence: dict[str, float] = {}
