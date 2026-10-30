"""Send a correctly signed WhatsApp webhook to a running server, to test the bot without Meta in the loop.

Usage:
  uv run python -m scripts.send_test_webhook --text "Is hafte kitna dena hai?"
  uv run python -m scripts.send_test_webhook --button g:c-1a2b3c4d5e6f:ignore
  uv run python -m scripts.send_test_webhook --image-id MEDIA_ID --phone 919810000001

Needs WHATSAPP_APP_SECRET set (same value in the server's .env). Replies go out through the Graph API, so with fake
credentials they fail (logged); the conversation is still recorded in the `messages` table.
"""
import argparse
import hashlib
import hmac
import json
import sys
import uuid

import httpx

from app.config import settings


def build_payload(phone: str, text: str | None = None, button_id: str | None = None, image_id: str | None = None,
                  audio_id: str | None = None) -> dict:
    base = {"from": phone, "id": f"wamid.test-{uuid.uuid4().hex[:12]}"}
    if text is not None:
        msg = {**base, "type": "text", "text": {"body": text}}
    elif button_id is not None:
        msg = {**base, "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "tap"}}}
    elif image_id is not None:
        msg = {**base, "type": "image", "image": {"id": image_id, "mime_type": "image/jpeg"}}
    elif audio_id is not None:
        msg = {**base, "type": "audio", "audio": {"id": audio_id, "mime_type": "audio/ogg; codecs=opus"}}
    else:
        raise ValueError("give one of text, button_id, image_id, audio_id")
    return {"object": "whatsapp_business_account", "entry": [{"id": "test", "changes": [{"field": "messages", "value": {"messages": [msg]}}]}]}


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/webhooks/whatsapp")
    ap.add_argument("--phone", default="919810000001", help="sender, as Meta sends it (country code + number)")
    ap.add_argument("--secret", default=settings.whatsapp_app_secret)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--button")
    g.add_argument("--image-id")
    g.add_argument("--audio-id")
    a = ap.parse_args()
    if not a.secret:
        print("Set WHATSAPP_APP_SECRET (or pass --secret): the webhook rejects unsigned requests.")
        return 2
    body = json.dumps(build_payload(a.phone, a.text, a.button, a.image_id, a.audio_id)).encode()
    r = httpx.post(a.url, content=body, headers={"X-Hub-Signature-256": sign(a.secret, body), "Content-Type": "application/json"})
    print(r.status_code, r.text)
    return 0 if r.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
