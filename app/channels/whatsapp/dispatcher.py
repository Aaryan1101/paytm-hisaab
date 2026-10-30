"""Routes one inbound WhatsApp message to the right pipeline (text -> agent, photo/PDF -> ingest, voice -> voice, tap -> action)."""
import logging

from sqlmodel import Session, select

from app import clock
from app.ai import audio_convert
from app.ai.tools.context import ToolContext
from app.channels.base import Button
from app.ai.graph import pending as pending_actions
from app.ai.graph.confirmations import buttons_for
from app.channels.whatsapp import bill_cards, button_actions
from app.channels.whatsapp.client import WhatsAppClient, to_wa_number
from app.channels.whatsapp.payload import InboundMessage
from app.container import Container
from app.models import Merchant
from app.services import ingest_service, message_service
from app.services.errors import ServiceError

log = logging.getLogger(__name__)
UNREGISTERED = "Yeh number Hisaab par registered nahi hai."
TRY_AGAIN = "Abhi yeh nahi ho paya. Kripya thodi der baad dobara bhejein."


def find_merchant(session: Session, wa_phone: str) -> Merchant | None:
    last10 = "".join(c for c in wa_phone if c.isdigit())[-10:]
    return session.exec(select(Merchant).where(Merchant.phone == last10)).first()


class InboundDispatcher:
    def __init__(self, session: Session, container: Container, client: WhatsAppClient):
        self._s, self._c, self._client = session, container, client

    def handle(self, msg: InboundMessage) -> None:
        merchant = find_merchant(self._s, msg.from_phone)
        if merchant is None:
            self._client.send_text(msg.from_phone, UNREGISTERED)
            return
        try:
            self._route(merchant, msg)
        except ServiceError as e:
            self._reply(merchant, e.message)
        except Exception:
            log.exception("failed handling WhatsApp message %s", msg.message_id)
            self._reply(merchant, TRY_AGAIN)
        self._s.commit()

    # -- routing
    def _route(self, merchant: Merchant, msg: InboundMessage) -> None:
        if msg.kind == "text":
            self._text(merchant, msg.text)
        elif msg.kind in ("image", "document"):
            self._bill(merchant, msg)
        elif msg.kind == "audio":
            self._voice(merchant, msg)
        elif msg.kind == "button":
            self._reply(merchant, self._tap(merchant, msg.button_id or ""))

    def _ctx(self, merchant: Merchant) -> ToolContext:
        return ToolContext(self._s, merchant.id, merchant.role, clock.today(), clock.now(), self._c.notifier(self._s),
                           self._c.media, self._c.reminders)

    def _tap(self, merchant: Merchant, button_id: str) -> str:
        """'g:<thread>:<choice>' resumes a pending confirmation; anything else is a legacy stateless button."""
        parts = button_id.split(":")
        if len(parts) == 3 and parts[0] == "g":
            return self._c.confirmations.resume(self._s, self._c.notifier(self._s), merchant.id, parts[1], parts[2])
        return button_actions.handle(self._s, self._c.notifier(self._s), merchant.id, button_id)

    def _reply(self, merchant: Merchant, text: str, pending: pending_actions.PendingAction | None = None,
               trace: dict | None = None) -> None:
        buttons: list[Button] | None = None
        if pending is not None:
            buttons = buttons_for(self._c.confirmations.start(merchant.id, pending), pending.options)
        self._c.notifier(self._s).send(merchant.id, text, buttons, trace)

    def _text(self, merchant: Merchant, text: str) -> None:
        history = message_service.recent_history(self._s, merchant.id, "whatsapp")
        message_service.log_message(self._s, merchant.id, "whatsapp", "in", text)
        reply = self._c.agent.respond(self._ctx(merchant), text, "whatsapp", merchant.language, history)
        self._reply(merchant, reply.text, pending_actions.from_traces(reply.traces), reply.trace.to_dict())

    def _bill(self, merchant: Merchant, msg: InboundMessage) -> None:
        data, _ = self._client.download_media(msg.media_id)
        message_service.log_message(self._s, merchant.id, "whatsapp", "in", "[bill photo/PDF]")
        result = ingest_service.ingest_invoice(self._s, merchant.id, data, "whatsapp", self._c.extractor, self._c.media)
        text, pending = bill_cards.render(result)
        self._reply(merchant, text, pending)

    def _voice(self, merchant: Merchant, msg: InboundMessage) -> None:
        data, _ = self._client.download_media(msg.media_id)
        reply = self._c.voice.handle(self._ctx(merchant), data, "voice.ogg")
        message_service.log_message(self._s, merchant.id, "whatsapp", "in", f"[voice] {reply.transcript}")
        self._reply(merchant, reply.text, pending_actions.from_traces(reply.traces), reply.trace)
        self._send_voice_note(merchant, reply.audio_url)

    def _send_voice_note(self, merchant: Merchant, audio_url: str | None) -> None:
        if not audio_url:
            return
        try:
            wav = next(self._c.media.root.joinpath("audio").glob(audio_url.rsplit("/", 1)[-1])).read_bytes()
            media_id = self._client.upload_media(audio_convert.to_ogg_opus(wav), "audio/ogg")
            self._client.send_audio(to_wa_number(merchant.phone), media_id)
        except Exception:
            log.exception("voice note reply could not be sent; text reply already delivered")
