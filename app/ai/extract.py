"""Reads a bill: preprocess, Document AI extraction, map to Invoice."""
from dataclasses import dataclass

from app.ai import invoice_mapper, preprocess
from app.ai.invoice_schema import INVOICE_SCHEMA
from app.ai.sarvam_port import DocAIPort
from app.ai.structuring import LlmStructurer
from app.models.schemas import Invoice


@dataclass(frozen=True)
class Extraction:
    invoice: Invoice
    raw: dict
    derived: frozenset[str]
    dropped_lines: int
    handwritten: bool


class InvoiceExtractor:
    def __init__(self, docai: DocAIPort, structurer: LlmStructurer | None = None):
        self._docai, self._structurer = docai, structurer

    def extract(self, data: bytes) -> Extraction:
        payload, content_type, filename = preprocess.prepare(data)
        raw = self._docai.extract(payload, filename, INVOICE_SCHEMA, content_type=content_type)
        return self._build(raw)

    def extract_from_text(self, ocr_text: str) -> Extraction:
        if self._structurer is None:
            raise RuntimeError("No LLM structurer configured")
        return self._build(self._structurer.structure(ocr_text))

    @staticmethod
    def _build(raw: dict) -> Extraction:
        m = invoice_mapper.map_invoice(raw)
        return Extraction(m.invoice, raw, frozenset(m.derived), m.dropped_lines, m.handwritten)
