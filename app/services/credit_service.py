"""Consent, offer preview, offer issue and acceptance (mock lender)."""
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.engine import credit as credit_engine
from app.models import Alert, CollectionIn, Consent, CreditOffer
from app.services import forecast_service, score_service
from app.services.errors import ConsentRequired, Invalid, NotFound

CONSENT_DAYS = 30
REQUIRED_SCOPE = {"gst_data", "bank_data"}
HISTORY_CAP_DAYS = 90


def grant_consent(session: Session, merchant_id: int, scope: list[str], now: datetime) -> Consent:
    consent = Consent(merchant_id=merchant_id, scope=scope, granted_at=now, expires_at=now + timedelta(days=CONSENT_DAYS))
    session.add(consent)
    session.flush()
    return consent


def active_consent(session: Session, merchant_id: int, now: datetime) -> Consent | None:
    for c in session.exec(select(Consent).where(Consent.merchant_id == merchant_id).order_by(Consent.id.desc())).all():
        if c.expires_at > now and REQUIRED_SCOPE <= set(c.scope):
            return c
    return None


def _avg_monthly_collections(session: Session, merchant_id: int, today: date, history_days: int) -> float:
    window = min(max(history_days, 1), HISTORY_CAP_DAYS)
    since = today - timedelta(days=window)
    total = sum(c.amount for c in session.exec(select(CollectionIn).where(
        CollectionIn.merchant_id == merchant_id, CollectionIn.payer_merchant_id == None,  # noqa: E711
        CollectionIn.received_at >= since)).all())
    return total / window * 30


def preview(session: Session, merchant_id: int, today: date) -> tuple[credit_engine.CreditDecision, score_service.ScoreReport]:
    report = score_service.get_score(session, merchant_id, today)
    shortfall = forecast_service.get_forecast(session, merchant_id, today).shortfall_amount
    fraud = session.exec(select(Alert).where(Alert.merchant_id == merchant_id, Alert.type == "duplicate_payment",
                                             Alert.status == "open")).first() is not None
    decision = credit_engine.decide(report.result.score, report.inputs.history_days,
                                    _avg_monthly_collections(session, merchant_id, today, report.inputs.history_days),
                                    shortfall, fraud)
    return decision, report


def create_offer(session: Session, merchant_id: int, today: date, now: datetime) -> tuple[CreditOffer | None, credit_engine.CreditDecision]:
    consent = active_consent(session, merchant_id, now)
    if consent is None:
        raise ConsentRequired("Share your GST and bank data with the lender to see your offer.")
    decision, report = preview(session, merchant_id, today)
    if not decision.eligible:
        return None, decision
    for old in session.exec(select(CreditOffer).where(CreditOffer.merchant_id == merchant_id,
                                                      CreditOffer.status == "offered")).all():
        session.delete(old)
    offer = CreditOffer(merchant_id=merchant_id, limit_amount=decision.limit, rate_apr_min=decision.apr_min,
                        rate_apr_max=decision.apr_max, tenure_days=decision.tenure_days,
                        reasons=[r.text_en for r in report.result.reasons], consent_id=consent.id)
    session.add(offer)
    session.flush()
    return offer, decision


def accept_offer(session: Session, merchant_id: int, offer_id: int) -> CreditOffer:
    offer = session.get(CreditOffer, offer_id)
    if offer is None or offer.merchant_id != merchant_id:
        raise NotFound("Offer not found")
    if offer.status != "offered":
        raise Invalid(f"Offer is already {offer.status}")
    offer.status = "accepted"
    session.add(offer)
    session.flush()
    return offer


def accepted_offer(session: Session, merchant_id: int) -> CreditOffer | None:
    return session.exec(select(CreditOffer).where(CreditOffer.merchant_id == merchant_id,
                                                  CreditOffer.status == "accepted").order_by(CreditOffer.id.desc())).first()
