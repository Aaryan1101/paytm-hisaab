from datetime import datetime
from app.models.clock import utc_now

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class SupplierQuery(SQLModel, table=True):
    """A question a retailer asked a supplier about a bill ("is this a duplicate?")."""
    __tablename__ = "supplier_queries"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    supplier_id: int = Field(foreign_key="suppliers.id")
    invoice_id: int = Field(foreign_key="invoices.id")
    text: str
    status: str = "open"  # open | answered
    answer: str | None = None  # duplicate | new_bill
    created_at: NaiveDatetime = Field(default_factory=utc_now)
