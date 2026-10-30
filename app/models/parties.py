from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class Merchant(SQLModel, table=True):
    __tablename__ = "merchants"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    role: str  # retailer | wholesaler | distributor
    gst_scheme: str  # composition | regular
    turnover_band: str
    phone: str
    gstin: str | None = None
    language: str = "hi"
    opening_balance: float = 0  # mock bank balance used by the forecast
    share_score: bool = False   # retailer opted in to share Hisaab Score with distributors


class Supplier(SQLModel, table=True):
    __tablename__ = "suppliers"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    name: str
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    gstin: str | None = None
    gstin_status: str = "active"  # active | cancelled | not_filing
    phone: str | None = None
    payee_vpa: str | None = None
    linked_merchant_id: int | None = Field(default=None, foreign_key="merchants.id")
