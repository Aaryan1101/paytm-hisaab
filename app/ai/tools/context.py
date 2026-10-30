from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlmodel import Session

from app.channels.base import Notifier
from app.storage import MediaStore


@dataclass
class ToolContext:
    """Everything a tool handler may use. Handlers never reach for globals."""
    session: Session
    merchant_id: int
    role: str  # retailer | wholesaler | distributor
    today: date
    now: datetime
    notifier: Notifier
    media: MediaStore | None = None
    reminder_drafter: Callable[..., str] | None = None
