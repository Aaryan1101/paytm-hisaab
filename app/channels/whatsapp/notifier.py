"""Sends outbound messages to merchants over WhatsApp, logging each one in the conversation history."""
import logging

from sqlmodel import Session

from app.channels.base import Button
from app.channels.whatsapp.client import WhatsAppClient, to_wa_number
from app.models import Merchant
from app.services import message_service

log = logging.getLogger(__name__)


class WhatsAppNotifier:
    def __init__(self, client: WhatsAppClient, session: Session):
        self._client, self._session = client, session

    def send(self, merchant_id: int, text: str, buttons: list[Button] | None = None, trace: dict | None = None) -> None:
        suffix = "" if not buttons else "  [" + " | ".join(b.title for b in buttons) + "]"
        message_service.log_message(self._session, merchant_id, "whatsapp", "out", text + suffix, trace=trace)
        merchant = self._session.get(Merchant, merchant_id)
        if merchant is None:
            return
        try:  # a delivery failure must not undo the business action that triggered the message
            self._client.send_buttons(to_wa_number(merchant.phone), text, buttons or [])
        except Exception:
            log.exception("WhatsApp send to merchant %s failed", merchant_id)
