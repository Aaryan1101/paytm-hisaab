"""FastAPI dependencies: DB session, AI container, merchant lookup and role guards, tool context."""
from fastapi import Depends, Request
from sqlmodel import Session

from app import clock
from app.ai.tools.context import ToolContext
from app.container import Container
from app.db import get_session
from app.models import Merchant
from app.services.errors import NotFound


def get_container(request: Request) -> Container:
    return request.app.state.container


def merchant_or_404(session: Session, merchant_id: int) -> Merchant:
    m = session.get(Merchant, merchant_id)
    if m is None:
        raise NotFound("Merchant not found")
    return m


def get_merchant(merchant_id: int, session: Session = Depends(get_session)) -> Merchant:
    return merchant_or_404(session, merchant_id)


def get_distributor(distributor_id: int, session: Session = Depends(get_session)) -> Merchant:
    m = merchant_or_404(session, distributor_id)
    if m.role != "distributor":
        raise NotFound("Distributor not found")
    return m


def tool_context(session: Session, merchant: Merchant, container: Container) -> ToolContext:
    return ToolContext(session=session, merchant_id=merchant.id, role=merchant.role, today=clock.today(), now=clock.now(),
                       notifier=container.notifier(session), media=container.media, reminder_drafter=container.reminders)
