"""Fallback: have the LLM structure OCR text into the same shape Document AI extraction returns."""
import json
import re

from app.ai import prompts
from app.ai.invoice_schema import INVOICE_SCHEMA
from app.ai.sarvam_port import ChatPort


class LlmStructurer:
    def __init__(self, chat: ChatPort):
        self._chat = chat

    def structure(self, ocr_text: str) -> dict:
        system = prompts.load("structuring") + "\n\nSchema:\n" + json.dumps(INVOICE_SCHEMA)
        msg = self._chat.complete([{"role": "system", "content": system}, {"role": "user", "content": ocr_text}],
                                  temperature=0.0, max_tokens=3000)
        return _parse_json(msg.get("content") or "")


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM returned no JSON object")
    return json.loads(text[start:end + 1])
