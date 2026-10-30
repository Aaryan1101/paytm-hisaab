from datetime import datetime

from app import clock
from app.ai.tools.context import ToolContext
from app.channels.db_notifier import DbNotifier


def make_ctx(session, merchant, media=None, drafter=None) -> ToolContext:
    return ToolContext(session=session, merchant_id=merchant.id, role=merchant.role, today=clock.today(),
                       now=datetime(2026, 10, 31, 12, 0), notifier=DbNotifier(session), media=media, reminder_drafter=drafter)
