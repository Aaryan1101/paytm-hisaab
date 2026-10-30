from datetime import datetime
from app.models.clock import utc_now

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class PaymentDraft(SQLModel, table=True):
    """A payment the agent or user prepared. Nothing moves until the merchant confirms."""
    __tablename__ = "payment_drafts"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    supplier_id: int = Field(foreign_key="suppliers.id")
    amount: float
    source: str  # bank | credit
    status: str = "drafted"  # drafted | confirmed | cancelled
    upi_link: str | None = None
    created_at: NaiveDatetime = Field(default_factory=utc_now)
