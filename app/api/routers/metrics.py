from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.schemas.merchants import ExtractionAccuracyOut
from app.db import get_session
from app.services import invoice_service

router = APIRouter(tags=["metrics"])


@router.get("/metrics/extraction-accuracy", response_model=ExtractionAccuracyOut)
def extraction_accuracy(merchant_id: int | None = None, session: Session = Depends(get_session)):
    """The pitch-slide number: how often the merchant left the AI's key fields unchanged (invoice no., totals)."""
    st = invoice_service.extraction_stats(session, merchant_id)
    return ExtractionAccuracyOut(accuracy=st.accuracy, bills=st.bills, fields=st.fields)
