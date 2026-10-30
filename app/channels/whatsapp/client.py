"""WhatsApp Cloud API (Graph) client: send text / buttons / audio, upload and download media."""
import httpx

from app.channels.base import Button

GRAPH = "https://graph.facebook.com/v20.0"
MAX_BUTTONS, MAX_TITLE, MAX_BODY = 3, 20, 1024


class WhatsAppError(Exception):
    pass


def to_wa_number(phone: str) -> str:
    """Meta wants country code + number, digits only. Our merchants store 10-digit Indian numbers."""
    digits = "".join(c for c in phone if c.isdigit())
    return "91" + digits if len(digits) == 10 else digits


class WhatsAppClient:
    def __init__(self, access_token: str, phone_number_id: str, http: httpx.Client | None = None):
        self._phone_id = phone_number_id
        self._http = http or httpx.Client(timeout=30)
        self._auth = {"Authorization": f"Bearer {access_token}"}

    def _send(self, payload: dict) -> None:
        r = self._http.post(f"{GRAPH}/{self._phone_id}/messages", headers=self._auth,
                            json={"messaging_product": "whatsapp", **payload})
        if r.is_error:
            raise WhatsAppError(f"send failed {r.status_code}: {r.text[:200]}")

    def send_text(self, to: str, text: str) -> None:
        self._send({"to": to, "type": "text", "text": {"body": text}})

    def send_buttons(self, to: str, text: str, buttons: list[Button]) -> None:
        if not buttons:
            return self.send_text(to, text)
        self._send({"to": to, "type": "interactive", "interactive": {
            "type": "button", "body": {"text": text[:MAX_BODY]},
            "action": {"buttons": [{"type": "reply", "reply": {"id": b.id, "title": b.title[:MAX_TITLE]}} for b in buttons[:MAX_BUTTONS]]}}})

    def send_audio(self, to: str, media_id: str) -> None:
        self._send({"to": to, "type": "audio", "audio": {"id": media_id}})

    def upload_media(self, data: bytes, mime_type: str) -> str:
        r = self._http.post(f"{GRAPH}/{self._phone_id}/media", headers=self._auth, data={"messaging_product": "whatsapp", "type": mime_type},
                            files={"file": ("reply", data, mime_type)})
        if r.is_error:
            raise WhatsAppError(f"upload failed {r.status_code}: {r.text[:200]}")
        return r.json()["id"]

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        meta = self._http.get(f"{GRAPH}/{media_id}", headers=self._auth)
        if meta.is_error:
            raise WhatsAppError(f"media lookup failed {meta.status_code}")
        info = meta.json()
        blob = self._http.get(info["url"], headers=self._auth)
        if blob.is_error:
            raise WhatsAppError(f"media download failed {blob.status_code}")
        return blob.content, info.get("mime_type", "application/octet-stream")
