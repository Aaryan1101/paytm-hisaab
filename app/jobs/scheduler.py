"""Runs the proactive jobs in the background. Safe to call as often as you like: every send is claimed once."""
import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime

from sqlmodel import Session

from app.container import Container
from app.jobs import notifications

log = logging.getLogger(__name__)
MONDAY = 0


def tick(session_factory: Callable[[], AbstractContextManager[Session]], container: Container, now: datetime,
         hour: int = 9) -> list[notifications.Sent]:
    """One pass. Daily jobs wait until `hour`; the digest only goes out on Mondays."""
    if now.hour < hour:
        return []
    with session_factory() as session:
        notifier = container.notifier(session)
        sent = notifications.send_due_tomorrow(session, notifier, now.date())
        if now.weekday() == MONDAY:
            sent += notifications.send_weekly_digest(session, notifier, now.date())
        session.commit()
    return sent


async def run_forever(job: Callable[[], object], interval_s: float, stop: asyncio.Event | None = None) -> None:
    """Call `job` (in a thread, so it never blocks the server) every `interval_s` until `stop` is set or the task is cancelled."""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            await asyncio.to_thread(job)
        except Exception:  # a failed pass must not kill the loop; the next one retries
            log.exception("scheduled jobs failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass
