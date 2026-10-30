from datetime import date

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class InvoiceRow(SQLModel, table=True):
    __tablename__ = "invoices"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    supplier_id: int | None = Field(default=None, foreign_key="suppliers.id", index=True)
    invoice_no: str
    invoice_date: date
    due_date: date | None = None
    taxable_total: float
    tax_total: float
    grand_total: float
    bill_type: str
    source: str  # whatsapp | app | distributor
    image_url: str | None = None
    raw_json: dict | None = Field(default=None, sa_column=Column(JSON))
    confirmed: bool = False
    status: str = "open"  # open | part_paid | paid | disputed
    amount_settled: float = 0  # matched payments plus applied credit notes
    ims_action: str | None = None
    ims_reason: str | None = None


class InvoiceLineRow(SQLModel, table=True):
    __tablename__ = "invoice_lines"
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoices.id", index=True)
    description: str
    hsn: str | None = None
    qty: float | None = None
    rate: float | None = None
    taxable_value: float
    gst_rate: float | None = None
    cgst: float = 0
    sgst: float = 0
    igst: float = 0
