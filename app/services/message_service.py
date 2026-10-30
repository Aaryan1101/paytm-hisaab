"""Conversation log and soundbox-style event feed."""
from sqlmodel import Session, select

from app.models import Message


def log_message(session: Session, merchant_id: int, channel: str, direction: str, text: str,
                audio_url: str | None = None, tool_calls: list | None = None, trace: dict | None = None) -> Message:
    msg = Message(merchant_id=merchant_id, channel=channel, direction=direction, text=text, audio_url=audio_url,
                  tool_calls_json=tool_calls, trace_json=trace)
    session.add(msg)
    session.flush()
    return msg


def push_event(session: Session, merchant_id: int, text: str) -> Message:
    return log_message(session, merchant_id, "soundbox", "out", text)


def list_events(session: Session, merchant_id: int, after_id: int = 0) -> list[Message]:
    return list(session.exec(select(Message).where(Message.merchant_id == merchant_id, Message.channel == "soundbox",
                                                   Message.id > after_id).order_by(Message.id)).all())


def recent_history(session: Session, merchant_id: int, channel: str, limit: int = 6) -> list[dict]:
    """Last few turns as chat messages (oldest first), so short follow-ups like "haan" keep their context."""
    rows = list(session.exec(select(Message).where(Message.merchant_id == merchant_id, Message.channel == channel)
                             .order_by(Message.id.desc()).limit(limit)).all())
    return [{"role": "user" if m.direction == "in" else "assistant", "content": m.text} for m in reversed(rows)]
