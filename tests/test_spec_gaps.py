"""Features added to close gaps against the product spec: supplier status, credit-note endpoints, match confirmation,
retailer detail, editable reminders, accuracy metric, cash balance."""
import io
import json
from datetime import datetime

import pytest
from PIL import Image
from sqlmodel import select

from app import clock
from app.ai.router import Route, route
from app.engine.validate import supplier_status_issue
from app.models import CollectionIn, InvoiceRow, Match, Merchant, Message, Supplier
from app.services import distributor_service, settlement_service
from tests.fakes import s1_bill, text, tool_call

IMG = io.BytesIO()
Image.new("RGB", (400, 300), (210, 200, 190)).save(IMG, "JPEG")
PHOTO = IMG.getvalue()


def upload(c, mid):
    return c.post("/invoices/ingest", data={"merchant_id": mid}, files={"file": ("b.jpg", PHOTO, "image/jpeg")}).json()


def inv(s, no):
    return s.exec(select(InvoiceRow).where(InvoiceRow.invoice_no == no)).one()


# ---- supplier status (spec 8.1)
@pytest.mark.parametrize("status,severity", [("cancelled", "high"), ("not_filing", "warn")])
def test_risky_supplier_status_raises_issue(status, severity):
    i = supplier_status_issue(status)
    assert i.code == "supplier_risk" and i.severity == severity and i.message_en and i.message_hi


def test_active_supplier_has_no_status_issue():
    assert supplier_status_issue("active") is None


def test_ingest_flags_a_bill_from_a_cancelled_supplier(api):
    c, s, ctx, fakes = api
    sharma = ctx.ramesh_suppliers["Sharma Traders"]
    sharma.gstin_status = "cancelled"
    s.add(sharma)
    fakes.docai.result = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-7001", "invoice_date": "20/09/2026"}
    r = upload(c, ctx.ramesh.id)
    risk = next(i for i in r["issues"] if i["code"] == "supplier_risk")
    assert risk["severity"] == "high" and "cancelled" in risk["message_en"]
    alerts = c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "supplier_risk"}).json()
    assert alerts and alerts[0]["invoice_id"] == r["invoice_id"]


def test_ingest_from_an_active_supplier_has_no_risk_issue(api):
    c, s, ctx, fakes = api
    fakes.docai.result = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-7002", "invoice_date": "20/09/2026"}
    assert not [i for i in upload(c, ctx.ramesh.id)["issues"] if i["code"] == "supplier_risk"]


# ---- retailer asks for a credit note (REST)
def test_request_credit_note_endpoint(api):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    r = c.post(f"/invoices/{i.id}/request-credit-note", params={"merchant_id": ctx.ramesh.id}, json={"amount": 1000})
    assert r.status_code == 200 and r.json()["status"] == "expected" and r.json()["amount"] == 1000 and r.json()["invoice_id"] == i.id
    again = c.post(f"/invoices/{i.id}/request-credit-note", params={"merchant_id": ctx.ramesh.id}, json={"amount": 1000}).json()
    assert again["id"] == r.json()["id"]
    msg = s.exec(select(Message).where(Message.merchant_id == ctx.vikas.id)).all()[-1].text
    assert "credit note" in msg


def test_request_credit_note_validation_and_scoping(api):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    assert c.post(f"/invoices/{i.id}/request-credit-note", params={"merchant_id": ctx.ramesh.id}, json={"amount": 0}).status_code == 422
    assert c.post(f"/invoices/{i.id}/request-credit-note", params={"merchant_id": ctx.neha.id}, json={"amount": 5}).status_code == 404


# ---- distributor issues a credit note
def test_distributor_credit_note_reduces_what_the_retailer_owes_and_notifies(api):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    before = c.get(f"/merchants/{ctx.ramesh.id}/dues", params={"period": "week"}).json()["total"]
    r = c.post(f"/distributors/{ctx.vikas.id}/credit-notes", json={"retailer_id": ctx.ramesh.id, "invoice_id": i.id, "amount": 2000})
    assert r.status_code == 200 and r.json()["status"] == "applied"  # reconciliation applies it straight away
    assert c.get(f"/merchants/{ctx.ramesh.id}/dues", params={"period": "week"}).json()["total"] == before - 2000
    assert "credit note jaari kiya" in s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id)).all()[-1].text


def test_issuing_fulfils_the_retailers_earlier_request(api):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    asked = c.post(f"/invoices/{i.id}/request-credit-note", params={"merchant_id": ctx.ramesh.id}, json={"amount": 1000}).json()
    done = c.post(f"/distributors/{ctx.vikas.id}/credit-notes", json={"retailer_id": ctx.ramesh.id, "invoice_id": i.id, "amount": 1000}).json()
    assert done["credit_note_id"] == asked["id"]


def test_issued_credit_note_persists_through_reconcile(api):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    c.post(f"/distributors/{ctx.vikas.id}/credit-notes", json={"retailer_id": ctx.ramesh.id, "invoice_id": i.id, "amount": 2000})
    for _ in range(2):
        c.post("/reconcile/run", params={"merchant_id": ctx.ramesh.id})
    assert c.get(f"/merchants/{ctx.ramesh.id}/dues", params={"period": "week"}).json()["total"] == 112_400 - 2000


@pytest.mark.parametrize("retailer,amount,code", [("ramesh", 50_000, 422), ("ramesh", -1, 422), ("neha", 100, 404)])
def test_distributor_credit_note_validation(api, retailer, amount, code):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    rid = ctx.ramesh.id if retailer == "ramesh" else ctx.neha.id
    assert c.post(f"/distributors/{ctx.vikas.id}/credit-notes", json={"retailer_id": rid, "invoice_id": i.id, "amount": amount}).status_code == code


def test_only_a_distributor_can_issue_credit_notes(api):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    assert c.post(f"/distributors/{ctx.ramesh.id}/credit-notes", json={"retailer_id": ctx.ramesh.id, "invoice_id": i.id, "amount": 5}).status_code == 404


# ---- "Confirm?" matches (retailer side)
def test_uncertain_matches_are_listed_and_confirming_sticks(api):
    c, s, ctx, _ = api
    pending = c.get(f"/merchants/{ctx.ramesh.id}/matches/pending").json()
    fuzzy = next(p for p in pending if p["invoice_no"] == "ST-2260")   # S7: matched via a fuzzy payee name
    assert fuzzy["confidence"] < 0.9 and fuzzy["counterparty"] == "Sharma Traders"
    assert "ST-2250" in [p["invoice_no"] for p in pending]              # the short-paid bill was only a partial match
    mid = fuzzy["match_id"]
    assert c.post(f"/merchants/{ctx.ramesh.id}/matches/{mid}/confirm").json() == {"ok": True}
    assert mid not in [p["match_id"] for p in c.get(f"/merchants/{ctx.ramesh.id}/matches/pending").json()]
    c.post("/reconcile/run", params={"merchant_id": ctx.ramesh.id})
    kept = s.get(Match, mid)
    assert kept is not None and kept.method == "manual" and kept.confirmed


def test_confirm_match_is_scoped_to_its_owner(api):
    c, s, ctx, _ = api
    mid = c.get(f"/merchants/{ctx.ramesh.id}/matches/pending").json()[0]["match_id"]
    assert c.post(f"/merchants/{ctx.neha.id}/matches/{mid}/confirm").status_code == 404
    assert c.post(f"/merchants/{ctx.ramesh.id}/matches/999999/confirm").status_code == 404


def test_pending_matches_are_sorted_least_sure_first(api):
    c, _, ctx, _ = api
    conf = [p["confidence"] for p in c.get(f"/merchants/{ctx.ramesh.id}/matches/pending").json()]
    assert conf == sorted(conf)


# ---- "Confirm?" matches (distributor side)
def partial_receipt(s, ctx):
    """A receipt for half of an open bill: the engine can only guess, so it needs confirming."""
    row = next(r for r in distributor_service.receivables(s, ctx.vikas.id, clock.today()) if r.retailer_id != ctx.ramesh.id and r.overdue_amount > 0)
    # partial receipts are applied to the OLDEST open bill first
    open_inv = min((i for i in settlement_service.distributor_invoices(s, ctx.vikas.id) if i.merchant_id == row.retailer_id and i.status == "open"),
                   key=lambda i: (i.invoice_date, i.id))
    col = CollectionIn(merchant_id=ctx.vikas.id, payer_merchant_id=row.retailer_id, amount=open_inv.grand_total / 2,
                       received_at=datetime(2026, 10, 30, 12), payer_vpa="x@y", net_amount=open_inv.grand_total / 2, utr="UTR-PARTIAL")
    s.add(col)
    s.flush()
    settlement_service.reconcile_distributor(s, ctx.vikas.id)
    return open_inv, col


def test_distributor_sees_and_confirms_uncertain_receipt_matches(api):
    c, s, ctx, _ = api
    open_inv, col = partial_receipt(s, ctx)
    pending = c.get(f"/distributors/{ctx.vikas.id}/matches/pending").json()
    mine = next(p for p in pending if p["invoice_id"] == open_inv.id)
    assert mine["method"] == "partial" and mine["confidence"] == 0.8
    settled_before = s.get(InvoiceRow, open_inv.id).amount_settled
    assert c.post(f"/distributors/{ctx.vikas.id}/matches/{mine['match_id']}/confirm").status_code == 200
    settlement_service.reconcile_distributor(s, ctx.vikas.id)
    settlement_service.reconcile_distributor(s, ctx.vikas.id)
    s.refresh(open_inv)
    assert s.get(Match, mine["match_id"]).method == "manual"
    assert open_inv.amount_settled == settled_before == open_inv.grand_total / 2  # not applied a second time


def test_settlements_expose_match_ids_confidence_and_payer(api):
    c, s, ctx, _ = api
    open_inv, _ = partial_receipt(s, ctx)
    rows = c.get(f"/distributors/{ctx.vikas.id}/settlements").json()
    row = next(r for r in rows if r["collection_id"] and any(m["match_id"] for m in r["matched"]) and r["payer_id"] == open_inv.merchant_id and not r["matched"][0]["confirmed"])
    assert row["matched"][0]["confidence"] == 0.8 and row["payer_name"]


def test_distributor_cannot_confirm_retailer_side_matches(api):
    c, s, ctx, _ = api
    retailer_match = c.get(f"/merchants/{ctx.ramesh.id}/matches/pending").json()[0]["match_id"]
    assert c.post(f"/distributors/{ctx.vikas.id}/matches/{retailer_match}/confirm").status_code == 404


# ---- retailer detail + open queries
def test_retailer_detail_has_bills_receipts_and_summary(api):
    c, s, ctx, _ = api
    d = c.get(f"/distributors/{ctx.vikas.id}/retailers/{ctx.ramesh.id}").json()
    assert d["name"] == "Ramesh General Store" and d["reason_en"]
    dates = [i["invoice_date"] for i in d["invoices"]]
    assert dates == sorted(dates, reverse=True) and {"ST-2302", "ST-2308"} <= {i["invoice_no"] for i in d["invoices"]}
    assert d["receipts"] and all(r["payer_id"] == ctx.ramesh.id for r in d["receipts"])
    assert d["open_queries"] == []


def test_retailer_question_appears_for_the_distributor_until_answered(api):
    c, s, ctx, _ = api
    i = inv(s, "ST-2302")
    q = c.post(f"/invoices/{i.id}/ask-supplier", params={"merchant_id": ctx.ramesh.id}).json()
    detail = c.get(f"/distributors/{ctx.vikas.id}/retailers/{ctx.ramesh.id}").json()
    assert [x["query_id"] for x in detail["open_queries"]] == [q["id"]] and detail["open_queries"][0]["invoice_no"] == "ST-2302"
    assert [x["query_id"] for x in c.get(f"/distributors/{ctx.vikas.id}/queries").json()] == [q["id"]]
    c.post(f"/queries/{q['id']}/answer", json={"answer": "new_bill"})
    assert c.get(f"/distributors/{ctx.vikas.id}/queries").json() == []


def test_unknown_retailer_detail_is_404(api):
    c, _, ctx, _ = api
    assert c.get(f"/distributors/{ctx.vikas.id}/retailers/{ctx.neha.id}").status_code == 404


# ---- editable reminders
def test_edited_reminder_text_is_what_gets_sent(api):
    c, s, ctx, fakes = api
    fakes.chat.script = lambda m, t: text("no figures")
    draft = c.post(f"/distributors/{ctx.vikas.id}/reminders", json={"language": "hi"}).json()["reminders"][0]
    rid = draft["retailer_id"]
    mine = "Namaste, kal tak payment kar dijiye. Dhanyavaad."
    out = c.post(f"/distributors/{ctx.vikas.id}/reminders", json={"language": "hi", "retailer_ids": [rid], "send": True, "texts": {str(rid): mine}}).json()
    assert out["reminders"][0]["text"] == mine and out["sent"] is True
    assert s.exec(select(Message).where(Message.merchant_id == rid)).all()[-1].text == mine


def test_preview_with_edits_returns_the_edited_text(api):
    c, _, ctx, fakes = api
    fakes.chat.script = lambda m, t: text("no figures")
    rid = c.post(f"/distributors/{ctx.vikas.id}/reminders", json={}).json()["reminders"][0]["retailer_id"]
    out = c.post(f"/distributors/{ctx.vikas.id}/reminders", json={"retailer_ids": [rid], "texts": {str(rid): "mera sandesh"}}).json()
    assert out["sent"] is False and out["reminders"][0]["text"] == "mera sandesh"


@pytest.mark.parametrize("texts", [{"999": "hi"}, {"36": "   "}, {"36": "x" * 1001}])
def test_bad_reminder_edits_are_rejected(api, texts):
    c, _, ctx, fakes = api
    fakes.chat.script = lambda m, t: text("no figures")
    r = c.post(f"/distributors/{ctx.vikas.id}/reminders", json={"retailer_ids": [36], "texts": texts, "send": True})
    assert r.status_code == 422


# ---- accuracy metric
def test_accuracy_is_null_before_any_read_bill_is_confirmed(api):
    c, _, _, _ = api
    assert c.get("/metrics/extraction-accuracy").json() == {"accuracy": None, "bills": 0, "fields": 0}


def test_accuracy_reflects_merchant_corrections(api):
    c, s, ctx, fakes = api
    fakes.docai.result = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-8001", "invoice_date": "20/09/2026"}
    a = upload(c, ctx.ramesh.id)["invoice_id"]
    c.post(f"/invoices/{a}/confirm", params={"merchant_id": ctx.ramesh.id})
    assert c.get("/metrics/extraction-accuracy", params={"merchant_id": ctx.ramesh.id}).json()["accuracy"] == 1.0
    fakes.docai.result = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-8002", "invoice_date": "20/08/2026"}
    b = upload(c, ctx.ramesh.id)["invoice_id"]
    c.post(f"/invoices/{b}/confirm", params={"merchant_id": ctx.ramesh.id}, json={"corrections": {"grand_total": 18_000}})
    m = c.get("/metrics/extraction-accuracy", params={"merchant_id": ctx.ramesh.id}).json()
    assert m["bills"] == 2 and 0 < m["accuracy"] < 1
    assert c.get("/metrics/extraction-accuracy", params={"merchant_id": ctx.neha.id}).json()["bills"] == 0


# ---- cash balance
def test_set_cash_balance_changes_the_forecast(api):
    c, _, ctx, _ = api
    assert c.get(f"/merchants/{ctx.ramesh.id}/forecast").json()["shortfall_amount"] == 38_000
    r = c.put(f"/merchants/{ctx.ramesh.id}/cash-balance", json={"amount": 500_000})
    assert r.json() == {"cash_balance": 500_000.0}
    assert c.get(f"/merchants/{ctx.ramesh.id}/forecast").json()["shortfall_amount"] == 0
    assert c.get(f"/merchants/{ctx.ramesh.id}/home").json()["cash_balance"] == 500_000.0


def test_cash_balance_unknown_merchant_is_404(api):
    assert api[0].put("/merchants/9999/cash-balance", json={"amount": 5}).status_code == 404


@pytest.mark.parametrize("phrase,amount", [("mere paas 40000 cash hai", 40000), ("cash in hand 2 lakh", 200000),
                                           ("mere paas paanch hazaar hai", 5000), ("bank balance 75,000", 75000)])
def test_router_understands_telling_the_balance(phrase, amount):
    assert route(phrase, "retailer") == Route("set_cash_balance", {"amount": amount})


def test_telling_the_balance_does_not_hijack_cash_payments_or_chitchat():
    assert route("Sharma ko paanch hazaar cash diye", "retailer").tool == "log_cash_payment"
    assert route("mere paas cash nahi hai", "retailer") is None


def test_agent_tool_sets_balance_and_replies(api):
    c, s, ctx, fakes = api
    fakes.chat.script = [tool_call("set_cash_balance", {"amount": 40000}), text("Theek hai, balance ₹40,000 note kar liya.")]
    r = c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "mere paas 40000 cash hai"}).json()
    assert r["tool_calls"][0]["result"]["cash_balance"] == 40000.0
    s.refresh(ctx.ramesh)
    assert ctx.ramesh.opening_balance == 40000.0


def test_set_cash_balance_is_a_retailer_tool_only(seeded):
    from app.ai.tools import registry
    names = lambda role: {t["function"]["name"] for t in registry.tool_specs(role)}
    assert "set_cash_balance" in names("retailer") and "set_cash_balance" not in names("distributor")
