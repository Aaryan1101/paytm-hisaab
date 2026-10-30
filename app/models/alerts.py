from datetime import datetime
from app.models.clock import utc_now

from sqlalchemy import JSON, Column
from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    type: str
    severity: str
    invoice_id: int | None = Field(default=None, foreign_key="invoices.id")
    supplier_id: int | None = Field(default=None, foreign_key="suppliers.id")
    payment_id: int | None = Field(default=None, foreign_key="payments_out.id")
    message_hi: str
    message_en: str
    status: str = "open"  # open | resolved


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    channel: str  # whatsapp | app | web | soundbox
    direction: str  # in | out
    text: str
    audio_url: str | None = None
    tool_calls_json: list | None = Field(default=None, sa_column=Column(JSON))
    trace_json: dict | None = Field(default=None, sa_column=Column(JSON))  # engine, path, per-step timing and tokens
    created_at: NaiveDatetime = Field(default_factory=utc_now)
