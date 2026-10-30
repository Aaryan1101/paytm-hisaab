from sqlmodel import Session

from app.channels.base import Button
from app.services import message_service


class DbNotifier:
    """Records outbound messages in the conversation log. Used when no live channel is configured, and in tests."""

    def __init__(self, session: Session, channel: str = "whatsapp"):
        self._session, self._channel = session, channel

    def send(self, merchant_id: int, text: str, buttons: list[Button] | None = None, trace: dict | None = None) -> None:
        suffix = "" if not buttons else "  [" + " | ".join(b.title for b in buttons) + "]"
        message_service.log_message(self._session, merchant_id, self._channel, "out", text + suffix, trace=trace)
