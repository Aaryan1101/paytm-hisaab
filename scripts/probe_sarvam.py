"""Smoke-test each Sarvam client once and print what comes back.

Usage: uv run python -m scripts.probe_sarvam chat | tts | stt <wav> | doc <image-or-pdf>
"""
import sys
from pathlib import Path

from app.ai.sarvam import Sarvam
from app.config import settings

TOOLS = [{"type": "function", "function": {
    "name": "get_dues", "description": "Dues for a period",
    "parameters": {"type": "object", "properties": {"period": {"type": "string", "enum": ["today", "week", "month"]}},
                   "required": ["period"]}}}]

INVOICE_SCHEMA = {"type": "object", "properties": {
    "supplier_name": {"type": "string", "description": "Name of the seller printed at the top of the bill"},
    "invoice_no": {"type": "string", "description": "Invoice or bill number"},
    "grand_total": {"type": "number", "description": "Final payable total in INR"}}}


def main() -> None:
    sarvam = Sarvam(settings)
    cmd = sys.argv[1]
    if cmd == "chat":
        print(sarvam.chat.complete([{"role": "user", "content": "Is hafte kitna dena hai?"}], tools=TOOLS))
    elif cmd == "tts":
        audio = sarvam.tts.synthesize("Is hafte ek lakh baarah hazaar dena hai.")
        Path(".cache/probe.wav").write_bytes(audio)
        print(f"wrote .cache/probe.wav ({len(audio)} bytes)")
    elif cmd == "stt":
        print(sarvam.stt.transcribe(Path(sys.argv[2]).read_bytes()))
    elif cmd == "doc":
        p = Path(sys.argv[2])
        ctype = "application/pdf" if p.suffix == ".pdf" else "image/jpeg"
        print(sarvam.docai.extract(p.read_bytes(), p.name, INVOICE_SCHEMA, content_type=ctype))


if __name__ == "__main__":
    main()
