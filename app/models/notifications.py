from pydantic import NaiveDatetime
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.clock import utc_now


class NotificationLog(SQLModel, table=True):
    """One row per proactive message sent. The unique key is what makes scheduled jobs safe to run repeatedly."""
    __tablename__ = "notification_log"
    __table_args__ = (UniqueConstraint("merchant_id", "kind", "key", name="uq_notification"),)
    id: int | None = Field(default=None, primary_key=True)
    merchant_id: int = Field(foreign_key="merchants.id", index=True)
    kind: str  # due_tomorrow | weekly_digest
    key: str
    sent_at: NaiveDatetime = Field(default_factory=utc_now)
