"""WhatsApp Cloud API webhook: verification handshake and inbound messages (processed after the 200 reply)."""
import json
import logging
from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractContextManager

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlmodel import Session

from app.api.deps import get_container
from app.channels.whatsapp import signature
from app.channels.whatsapp.dispatcher import InboundDispatcher
from app.channels.whatsapp.payload import InboundMessage, parse_webhook
from app.config import settings
from app.container import Container
from app.db import engine

log = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])
_SEEN: OrderedDict[str, None] = OrderedDict()  # Meta retries deliveries; process each message id once (per process)
_SEEN_MAX = 2000


def get_session_factory(request: Request) -> Callable[[], AbstractContextManager[Session]]:
    return getattr(request.app.state, "session_factory", None) or (lambda: Session(engine))


def _first_time(message_id: str) -> bool:
    if message_id in _SEEN:
        return False
    _SEEN[message_id] = None
    if len(_SEEN) > _SEEN_MAX:
        _SEEN.popitem(last=False)
    return True


def process(messages: list[InboundMessage], container: Container, session_factory) -> None:
    for msg in messages:
        if not _first_time(msg.message_id):
            continue
        with session_factory() as session:
            InboundDispatcher(session, container, container.whatsapp).handle(msg)


@router.get("/webhooks/whatsapp")
def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.whatsapp_verify_token:
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@router.post("/webhooks/whatsapp")
async def inbound(request: Request, background: BackgroundTasks, container: Container = Depends(get_container),
                  session_factory=Depends(get_session_factory)):
    body = await request.body()
    if not signature.verify(settings.whatsapp_app_secret, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "Bad signature")
    if container.whatsapp is None:
        raise HTTPException(503, "WhatsApp is not configured")
    try:
        messages = parse_webhook(json.loads(body))
    except ValueError:
        raise HTTPException(400, "Invalid JSON")
    background.add_task(process, messages, container, session_factory)
    return {"received": len(messages)}
