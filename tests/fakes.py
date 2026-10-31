"""Test doubles for the Sarvam ports."""
import json


class FakeChat:
    """Scripted chat: pass a list of assistant messages (returned in order) or a callable(messages, tools)->message."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def complete(self, messages, tools=None, temperature=0.2, max_tokens=2048, reasoning=False, tool_choice=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "tool_choice": tool_choice})
        if callable(self.script):
            return self.script(messages, tools)
        if not self.script:
            raise AssertionError("FakeChat script exhausted")
        return self.script.pop(0)


def text(content: str) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": None}


def tool_call(name: str, args: dict, id: str = "call_1") -> dict:
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class FakeDocAI:
    def __init__(self, result: dict):
        self.result, self.calls = result, []

    def extract(self, file, filename, schema, language="en-IN", content_type="image/jpeg"):
        self.calls.append({"filename": filename, "content_type": content_type, "size": len(file)})
        return self.result


class FakeStt:
    def __init__(self, transcript="Is hafte kitna dena hai?", language_code="hi-IN"):
        self.transcript, self.language_code, self.calls = transcript, language_code, []

    def transcribe(self, audio, filename="audio.wav", mode="codemix"):
        self.calls.append({"size": len(audio), "mode": mode})
        return {"transcript": self.transcript, "language_code": self.language_code}


class FakeTts:
    def __init__(self, audio=b"RIFFfakewav"):
        self.audio, self.calls = audio, []

    def synthesize(self, text, language_code="hi-IN"):
        self.calls.append({"text": text, "language_code": language_code})
        return self.audio


SHARMA_BILL = {
    "document_title": "Tax Invoice", "is_handwritten": False, "supplier_name": "Sharma Traders",
    "supplier_gstin": None, "buyer_gstin": None, "invoice_no": "ST-2291", "invoice_date": "28/10/2026",
    "due_date": "04/11/2026", "line_items": [
        {"description": "Biscuits Family Pack", "hsn": "1905", "qty": 100, "unit": "pkt", "rate": 40.0,
         "taxable_value": 4000.0, "gst_rate": 5, "cgst": 100.0, "sgst": 100.0},
        {"description": "Soap 100g", "hsn": "3401", "qty": 200, "unit": "pc", "rate": 38.0,
         "taxable_value": 7600.0, "gst_rate": 5, "cgst": 190.0, "sgst": 190.0}],
    "taxable_total": 11600.0, "tax_total": 580.0, "round_off": 0.0, "grand_total": 12180.0}


def s1_bill(supplier_gstin: str) -> dict:
    """The demo bill: same number as ST-2291 (already paid), Rs 18,640."""
    return {"document_title": "Tax Invoice", "supplier_name": "Sharma Traders", "supplier_gstin": supplier_gstin,
            "invoice_no": "ST-2291", "invoice_date": "28/10/2026", "due_date": "04/11/2026",
            "line_items": [{"description": "Biscuits Family Pack", "hsn": "1905", "qty": 1, "unit": "lot", "rate": 17752.38,
                            "taxable_value": 17752.38, "gst_rate": 5, "cgst": 443.81, "sgst": 443.81}],
            "taxable_total": 17752.38, "tax_total": 887.62, "round_off": 0, "grand_total": 18640.0}


class FakeWhatsApp:
    """Records what would be sent; serves canned media bytes."""

    def __init__(self, media: bytes = b"", mime: str = "image/jpeg"):
        self.media, self.mime = media, mime
        self.texts: list[tuple[str, str]] = []
        self.buttons: list[tuple[str, str, list]] = []
        self.audio: list[tuple[str, str]] = []
        self.uploads: list[tuple[int, str]] = []

    def send_text(self, to, text):
        self.texts.append((to, text))

    def send_buttons(self, to, text, buttons):
        (self.buttons if buttons else self.texts).append((to, text, buttons) if buttons else (to, text))

    def send_audio(self, to, media_id):
        self.audio.append((to, media_id))

    def upload_media(self, data, mime_type):
        self.uploads.append((len(data), mime_type))
        return "media-1"

    def download_media(self, media_id):
        return self.media, self.mime

    def all_text(self) -> str:
        return " | ".join([t[1] for t in self.texts] + [b[1] for b in self.buttons])
