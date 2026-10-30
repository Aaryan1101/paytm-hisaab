from datetime import date

from sqlmodel import Field, SQLModel


class ImsEntry(SQLModel, table=True):
    """One inward invoice a supplier has uploaded in GSTR-1 (mock of the GST portal's IMS list)."""
    __tablename__ = "ims_entries"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    month: str  # YYYY-MM
    supplier_gstin: str
    supplier_name: str
    invoice_no: str
    invoice_date: date
    taxable: float
    tax: float
    not_purchased: bool = False
    action: str | None = None  # accept | reject | pending (our suggestion)
    reason_en: str | None = None
    reason_hi: str | None = None
    itc_risk: bool = False
    user_override: bool = False  # merchant changed the suggestion; recomputing must not clobber it
    approved: bool = False
    invoice_id: int | None = Field(default=None, foreign_key="invoices.id")
