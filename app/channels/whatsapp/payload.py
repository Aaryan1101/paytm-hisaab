"""Parses Meta's webhook JSON into plain inbound messages. Status callbacks and unknown types are ignored."""
from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    from_phone: str
    kind: str  # text | image | audio | document | button
    text: str = ""
    media_id: str | None = None
    mime_type: str | None = None
    button_id: str | None = None


def parse_webhook(payload: dict) -> list[InboundMessage]:
    out: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in (change.get("value") or {}).get("messages", []) or []:
                parsed = _parse_one(m)
                if parsed:
                    out.append(parsed)
    return out


def _parse_one(m: dict) -> InboundMessage | None:
    base = {"message_id": m.get("id", ""), "from_phone": m.get("from", "")}
    kind = m.get("type")
    if kind == "text":
        return InboundMessage(**base, kind="text", text=(m.get("text") or {}).get("body", ""))
    if kind in ("image", "audio", "document"):
        media = m.get(kind) or {}
        return InboundMessage(**base, kind=kind, text=media.get("caption", ""), media_id=media.get("id"), mime_type=media.get("mime_type"))
    if kind == "interactive":
        reply = (m.get("interactive") or {})
        chosen = reply.get("button_reply") or reply.get("list_reply") or {}
        if chosen.get("id"):
            return InboundMessage(**base, kind="button", text=chosen.get("title", ""), button_id=chosen["id"])
    return None
