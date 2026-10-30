"""Bill ingestion: read, validate, find duplicates, store as an unconfirmed invoice, raise alerts."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.ai import confidence
from app.ai.extract import InvoiceExtractor
from app.ai.invoice_mapper import ExtractionError
from app.engine import gstin as gstin_engine
from app.engine.issues import Issue
from app.engine.validate import DUPLICATE_WINDOW_DAYS, validate_invoice
from app.models import InvoiceLineRow, InvoiceRow, Merchant, Supplier
from app.models.schemas import Invoice
from app.services import alert_service, invoice_loader, payment_dates
from app.services.errors import Unreadable
from app.services.supplier_lookup import find_supplier
from app.storage import MediaStore

DEFAULT_CREDIT_DAYS = 14


@dataclass(frozen=True)
class DuplicateInfo:
    invoice_id: int
    invoice_no: str
    invoice_date: date
    paid_on: date | None


@dataclass(frozen=True)
class IngestResult:
    invoice_id: int
    invoice: Invoice
    issues: list[Issue]
    field_confidence: dict[str, float]
    low_confidence_fields: list[str]
    duplicate: DuplicateInfo | None
    image_url: str | None


def ingest_invoice(session: Session, merchant_id: int, data: bytes, source: str, extractor: InvoiceExtractor,
                   media: MediaStore | None = None) -> IngestResult:
    try:
        extraction = extractor.extract(data)
    except ExtractionError as e:
        raise Unreadable(f"Could not read the bill ({', '.join(e.missing)}). Please send a clearer photo.") from e
    merchant = session.get(Merchant, merchant_id)
    invoice = extraction.invoice
    if invoice.buyer_gstin is None:
        invoice = invoice.model_copy(update={"buyer_gstin": merchant.gstin})

    issues = validate_invoice(invoice, invoice_loader.previous_invoices(session, merchant_id))
    supplier = _resolve_supplier(session, merchant_id, invoice)
    duplicate_row = _find_duplicate(session, merchant_id, supplier.id, invoice) if any(i.code == "possible_duplicate" for i in issues) else None
    conf = confidence.score_fields(invoice, issues, set(extraction.derived), extraction.handwritten)
    stored = media.save(data, "pdf" if data[:5] == b"%PDF-" else "jpg", "bills") if media else None

    row = InvoiceRow(
        merchant_id=merchant_id, supplier_id=supplier.id, invoice_no=invoice.invoice_no, invoice_date=invoice.invoice_date,
        due_date=invoice.due_date or invoice.invoice_date + timedelta(days=DEFAULT_CREDIT_DAYS),
        taxable_total=invoice.taxable_total, tax_total=invoice.tax_total, grand_total=invoice.grand_total,
        bill_type=invoice.bill_type, source=source, image_url=stored.url if stored else None, confirmed=False,
        status="disputed" if duplicate_row else "open",
        raw_json={**invoice.model_dump(mode="json"), "field_confidence": conf, "_docai": extraction.raw})
    session.add(row)
    session.flush()
    for li in invoice.line_items:
        session.add(InvoiceLineRow(invoice_id=row.id, description=li.description, hsn=li.hsn, qty=li.qty, rate=li.rate,
                                   taxable_value=li.taxable_value, gst_rate=li.gst_rate, cgst=li.cgst, sgst=li.sgst, igst=li.igst))
    for issue in issues:
        alert_service.add_alert(session, merchant_id, issue.code, issue.severity, issue.message_en, issue.message_hi,
                                invoice_id=row.id, supplier_id=supplier.id)
    session.flush()
    return IngestResult(row.id, invoice, issues, conf, confidence.low_confidence(conf, invoice),
                        _duplicate_info(session, duplicate_row), stored.url if stored else None)


def _resolve_supplier(session: Session, merchant_id: int, inv: Invoice) -> Supplier:
    if inv.supplier_gstin and gstin_engine.is_valid(inv.supplier_gstin):
        hit = session.exec(select(Supplier).where(Supplier.merchant_id == merchant_id,
                                                  Supplier.gstin == inv.supplier_gstin)).first()
        if hit:
            return hit
    hit = find_supplier(session, merchant_id, inv.supplier_name)
    if hit:
        return hit
    sup = Supplier(merchant_id=merchant_id, name=inv.supplier_name, gstin=inv.supplier_gstin)
    session.add(sup)
    session.flush()
    return sup


def _find_duplicate(session: Session, merchant_id: int, supplier_id: int, inv: Invoice) -> InvoiceRow | None:
    window = timedelta(days=DUPLICATE_WINDOW_DAYS)
    for r in session.exec(select(InvoiceRow).where(InvoiceRow.merchant_id == merchant_id, InvoiceRow.supplier_id == supplier_id,
                                                   InvoiceRow.confirmed == True)).all():  # noqa: E712
        if r.invoice_no == inv.invoice_no or (r.grand_total == inv.grand_total and abs(r.invoice_date - inv.invoice_date) <= window):
            return r
    return None


def _duplicate_info(session: Session, row: InvoiceRow | None) -> DuplicateInfo | None:
    if row is None:
        return None
    return DuplicateInfo(row.id, row.invoice_no, row.invoice_date, payment_dates.last_payment_dates(session, [row.id]).get(row.id))
