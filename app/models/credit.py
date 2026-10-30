from datetime import datetime

from sqlalchemy import JSON, Column
from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class Consent(SQLModel, table=True):
    __tablename__ = "consents"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    scope: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    granted_at: NaiveDatetime
    expires_at: NaiveDatetime


class CreditOffer(SQLModel, table=True):
    __tablename__ = "credit_offers"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    limit_amount: float
    rate_apr_min: float
    rate_apr_max: float
    tenure_days: int
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "offered"  # offered | accepted | declined
    consent_id: int | None = Field(default=None, foreign_key="consents.id")
