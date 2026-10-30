from fastapi import APIRouter, Depends, Response
from sqlmodel import Session, select

from app import clock
from app.api.deps import get_merchant
from app.api.schemas.merchants import (AlertOut, ConsentIn, ConsentOut, CreditOfferOut, DueItemOut, DuesOut,
                                       ForecastDayOut, ForecastOut, HomeOut, ImsEntryOut, ImsMissingOut, ImsOut,
                                       LedgerEntryOut, LedgerOut, MerchantOut, OverrideIn, ReasonOut, ScoreOut,
                                       SupplierSummaryOut)
from app.db import get_session
from app.models import Alert, Merchant, Supplier
from app.services import (alert_service, credit_service, dues_service, forecast_service, ims_service, ledger_service,
                          reconcile_service, register_export_service, score_service)
from app.services.errors import Invalid, NotFound

router = APIRouter(tags=["merchants"])


def _merchant(m: Merchant) -> MerchantOut:
    return MerchantOut(id=m.id, name=m.name, role=m.role, gst_scheme=m.gst_scheme, language=m.language)


def _alert(a: Alert) -> AlertOut:
    return AlertOut(id=a.id, type=a.type, severity=a.severity, message_en=a.message_en, message_hi=a.message_hi,
                    invoice_id=a.invoice_id, supplier_id=a.supplier_id, payment_id=a.payment_id, status=a.status)


def _forecast(f) -> ForecastOut:
    return ForecastOut(buffer=f.buffer, first_below_date=f.first_below_date, shortfall_date=f.shortfall_date,
                       shortfall_amount=f.shortfall_amount,
                       days=[ForecastDayOut(day=d.day, inflow=d.inflow, outflow=d.outflow, balance=d.balance, low=d.low, high=d.high)
                             for d in f.days])


@router.get("/merchants", response_model=list[MerchantOut])
def list_merchants(session: Session = Depends(get_session)):
    """The three demo personas (Ramesh, Neha, Vikas), for the merchant switcher."""
    return [_merchant(m) for m in session.exec(select(Merchant).where(Merchant.id <= 3).order_by(Merchant.id)).all()]


@router.get("/merchants/{merchant_id}", response_model=MerchantOut)
def get_one(m: Merchant = Depends(get_merchant)):
    return _merchant(m)


@router.get("/merchants/{merchant_id}/home", response_model=HomeOut)
def home(m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    today = clock.today()
    dues = dues_service.get_dues(session, m.id, today, "week")
    f = forecast_service.get_forecast(session, m.id, today)
    return HomeOut(merchant=_merchant(m), owe_this_week=dues.total, suppliers_due_this_week=len(dues.items),
                   alert_count=len(alert_service.list_alerts(session, m.id)),
                   score=score_service.get_score(session, m.id, today).result.score,
                   shortfall_date=f.shortfall_date, shortfall_amount=f.shortfall_amount, forecast=_forecast(f).days)


@router.get("/merchants/{merchant_id}/dues", response_model=DuesOut)
def dues(period: str = "week", m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    if period not in dues_service.PERIOD_DAYS:
        raise Invalid("period must be today, week or month")
    d = dues_service.get_dues(session, m.id, clock.today(), period)
    return DuesOut(period=d.period, total=d.total, items=[DueItemOut(supplier_id=i.supplier_id, supplier_name=i.supplier_name,
                                                                     amount=i.amount, next_due=i.next_due, invoice_nos=i.invoice_nos) for i in d.items])


@router.get("/merchants/{merchant_id}/suppliers", response_model=list[SupplierSummaryOut])
def suppliers(m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    open_by_supplier: dict[int, list] = {}
    for inv in dues_service.open_invoices(session, m.id):
        open_by_supplier.setdefault(inv.supplier_id, []).append(inv)
    alerted = {a.supplier_id for a in alert_service.list_alerts(session, m.id) if a.supplier_id}
    out = []
    for s in session.exec(select(Supplier).where(Supplier.merchant_id == m.id).order_by(Supplier.name)).all():
        invs = open_by_supplier.get(s.id, [])
        risk = "high" if s.gstin_status != "active" else "medium" if s.id in alerted else "low"
        out.append(SupplierSummaryOut(id=s.id, name=s.name, balance_due=round(sum(dues_service.remaining(i) for i in invs), 2),
                                      next_due=min((i.due_date for i in invs if i.due_date), default=None), risk=risk,
                                      gstin_status=s.gstin_status))
    return sorted(out, key=lambda x: (x.next_due is None, x.next_due))


@router.get("/merchants/{merchant_id}/suppliers/{supplier_id}/ledger", response_model=LedgerOut)
def ledger(supplier_id: int, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    led = ledger_service.supplier_ledger(session, m.id, supplier_id)
    if led is None:
        raise NotFound("Supplier not found")
    return LedgerOut(supplier_id=led.supplier_id, supplier_name=led.supplier_name, balance_due=led.balance_due,
                     entries=[LedgerEntryOut(day=e.day, kind=e.kind, ref=e.ref, amount=e.amount, balance=e.balance, status=e.status)
                              for e in led.entries], open_issues=[_alert(a) for a in led.open_issues])


@router.get("/merchants/{merchant_id}/alerts", response_model=list[AlertOut])
def alerts(type: str | None = None, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    return [_alert(a) for a in alert_service.list_alerts(session, m.id, type)]


@router.post("/merchants/{merchant_id}/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: int, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    alert = session.get(Alert, alert_id)
    if alert is None or alert.merchant_id != m.id:
        raise NotFound("Alert not found")
    alert_service.resolve_alert(session, alert_id)
    session.commit()
    return _alert(alert)


@router.post("/reconcile/run")
def run_reconcile(merchant_id: int, session: Session = Depends(get_session)):
    get_merchant(merchant_id, session)
    r = reconcile_service.reconcile_merchant(session, merchant_id)
    session.commit()
    return {"matches": len(r.matches), "unmatched_payments": len(r.unmatched_payment_ids), "unpaid_invoices": len(r.unpaid_invoice_ids)}


@router.get("/merchants/{merchant_id}/ims", response_model=ImsOut)
def ims(month: str, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    r = ims_service.get_ims(session, m.id, month)
    session.commit()
    return ImsOut(month=r.month, counts=r.counts(),
                  entries=[ImsEntryOut(id=e.id, supplier_name=e.supplier_name, invoice_no=e.invoice_no, invoice_date=e.invoice_date,
                                       taxable=e.taxable, tax=e.tax, action=e.action, reason_en=e.reason_en, reason_hi=e.reason_hi,
                                       itc_risk=e.itc_risk, approved=e.approved) for e in r.entries],
                  missing_from_ims=[ImsMissingOut(invoice_id=i.id, invoice_no=i.invoice_no, reason_en=x.reason_en, reason_hi=x.reason_hi)
                                    for i, x in r.missing])


@router.post("/merchants/{merchant_id}/ims/approve-all")
def ims_approve_all(month: str, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    n = ims_service.approve_all(session, m.id, month)
    session.commit()
    return {"approved": n, "note": "Saved in Hisaab only; filing on the GST portal needs a GSP integration."}


@router.post("/merchants/{merchant_id}/ims/{entry_id}/override")
def ims_override(entry_id: int, body: OverrideIn, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    e = ims_service.override_entry(session, m.id, entry_id, body.action)
    session.commit()
    return {"id": e.id, "action": e.action}


@router.get("/merchants/{merchant_id}/forecast", response_model=ForecastOut)
def forecast(days: int = 14, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    if not 1 <= days <= 60:
        raise Invalid("days must be between 1 and 60")
    return _forecast(forecast_service.get_forecast(session, m.id, clock.today(), days))


@router.get("/merchants/{merchant_id}/score", response_model=ScoreOut)
def score(m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    r = score_service.get_score(session, m.id, clock.today()).result
    return ScoreOut(score=r.score, factors=r.factors, reasons=[ReasonOut(factor=x.factor, positive=x.positive, text_en=x.text_en, text_hi=x.text_hi) for x in r.reasons])


@router.post("/merchants/{merchant_id}/consents", response_model=ConsentOut)
def grant_consent(body: ConsentIn, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    c = credit_service.grant_consent(session, m.id, body.scope, clock.now())
    session.commit()
    return ConsentOut(id=c.id, scope=c.scope, granted_at=c.granted_at, expires_at=c.expires_at)


@router.get("/merchants/{merchant_id}/credit-offer", response_model=CreditOfferOut)
def credit_offer(m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    offer, decision = credit_service.create_offer(session, m.id, clock.today(), clock.now())
    session.commit()
    if offer is None:
        return CreditOfferOut(eligible=False, reason=decision.reason)
    return CreditOfferOut(eligible=True, reason=decision.reason, offer_id=offer.id, limit=offer.limit_amount,
                          rate_apr_min=offer.rate_apr_min, rate_apr_max=offer.rate_apr_max, tenure_days=offer.tenure_days,
                          reasons=offer.reasons)


@router.post("/merchants/{merchant_id}/credit-offer/{offer_id}/accept", response_model=CreditOfferOut)
def accept_offer(offer_id: int, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    o = credit_service.accept_offer(session, m.id, offer_id)
    session.commit()
    return CreditOfferOut(eligible=True, reason="Accepted", offer_id=o.id, limit=o.limit_amount, rate_apr_min=o.rate_apr_min,
                          rate_apr_max=o.rate_apr_max, tenure_days=o.tenure_days, reasons=o.reasons)


@router.get("/merchants/{merchant_id}/register.csv")
def register(month: str, m: Merchant = Depends(get_merchant), session: Session = Depends(get_session)):
    name, text = register_export_service.purchase_register_csv(session, m.id, month)
    return Response(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
