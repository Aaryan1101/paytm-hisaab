import io

import pytest
from PIL import Image

from app.ai import audio_convert
from tests.fakes import FakeChat, s1_bill, text, tool_call

IMG = io.BytesIO()
Image.new("RGB", (500, 300), (220, 210, 200)).save(IMG, "JPEG")
PHOTO = IMG.getvalue()
WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64


def upload(client, merchant_id, source="whatsapp"):
    return client.post("/invoices/ingest", data={"merchant_id": merchant_id, "source": source},
                       files={"file": ("bill.jpg", PHOTO, "image/jpeg")})


# ---- basics
def test_health(api):
    assert api[0].get("/health").json() == {"ok": True}


def test_merchant_switcher_lists_the_three_personas(api):
    r = api[0].get("/merchants").json()
    assert [m["name"] for m in r] == ["Ramesh General Store", "Gupta Wholesale", "Sharma Traders"]


def test_unknown_merchant_is_404_with_error_code(api):
    r = api[0].get("/merchants/9999")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_home_screen_aggregate(api):
    c, _, ctx, _ = api
    h = c.get(f"/merchants/{ctx.ramesh.id}/home").json()
    assert h["owe_this_week"] == 112_400 and h["suppliers_due_this_week"] == 5
    assert h["shortfall_amount"] == 38_000 and h["shortfall_date"] == "2026-11-05" and len(h["forecast"]) == 14
    assert h["score"] >= 600 and h["alert_count"] >= 2


# ---- dues / suppliers / ledger / alerts
def test_dues_endpoint_and_validation(api):
    c, _, ctx, _ = api
    d = c.get(f"/merchants/{ctx.ramesh.id}/dues", params={"period": "week"}).json()
    assert d["total"] == 112_400 and d["items"][0]["supplier_name"] == "Gupta Oil Mills"
    assert c.get(f"/merchants/{ctx.ramesh.id}/dues", params={"period": "year"}).status_code == 422


def test_suppliers_list_with_risk_badges(api):
    c, _, ctx, _ = api
    rows = c.get(f"/merchants/{ctx.neha.id}/suppliers").json()
    assert next(r for r in rows if r["name"] == "Kanpur Plastics")["risk"] == "high"
    ramesh = c.get(f"/merchants/{ctx.ramesh.id}/suppliers").json()
    assert next(r for r in ramesh if r["name"] == "Sharma Traders")["risk"] == "medium"  # open alerts


def test_ledger_and_scoping(api):
    c, _, ctx, _ = api
    sid = ctx.ramesh_suppliers["Sharma Traders"].id
    led = c.get(f"/merchants/{ctx.ramesh.id}/suppliers/{sid}/ledger").json()
    assert led["balance_due"] == 73_800 and led["entries"]
    assert c.get(f"/merchants/{ctx.neha.id}/suppliers/{sid}/ledger").status_code == 404


def test_alerts_filter_and_resolve(api):
    c, _, ctx, _ = api
    rows = c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "missing_credit_note"}).json()
    assert len(rows) == 1 and "2,300" in rows[0]["message_en"]
    assert c.post(f"/merchants/{ctx.ramesh.id}/alerts/{rows[0]['id']}/resolve").json()["status"] == "resolved"
    assert c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "missing_credit_note"}).json() == []
    assert c.post(f"/merchants/{ctx.neha.id}/alerts/{rows[0]['id']}/resolve").status_code == 404


def test_reconcile_run(api):
    c, _, ctx, _ = api
    assert c.post("/reconcile/run", params={"merchant_id": ctx.ramesh.id}).json()["matches"] > 20


def test_confirm_payee_flow(api):
    c, _, ctx, _ = api
    alert = c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "confirm_payee"}).json()[0]
    r = c.post(f"/merchants/{ctx.ramesh.id}/payments/{alert['payment_id']}/confirm-payee", json={"supplier_id": alert["supplier_id"]})
    assert r.json() == {"ok": True}
    assert c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "confirm_payee"}).json() == []
    assert c.post(f"/merchants/{ctx.neha.id}/payments/{alert['payment_id']}/confirm-payee", json={"supplier_id": 1}).status_code == 404


# ---- ingest (S1, S3, S8)
def test_s1_duplicate_bill_over_http(api):
    c, _, ctx, fakes = api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    r = upload(c, ctx.ramesh.id)
    body = r.json()
    assert r.status_code == 200 and body["duplicate"]["invoice_no"] == "ST-2291" and body["duplicate"]["paid_on"] == "2026-10-12"
    assert any(i["code"] == "possible_duplicate" for i in body["issues"])
    assert body["invoice"]["grand_total"] == 18_640


def test_unreadable_bill_is_422_with_message(api):
    c, _, ctx, fakes = api
    fakes.docai.result = {"supplier_name": "X"}
    r = upload(c, ctx.ramesh.id)
    assert r.status_code == 422 and r.json()["error"] == "unreadable" and "invoice_no" in r.json()["message"]


def test_ingest_unknown_merchant(api):
    c, _, _, fakes = api
    fakes.docai.result = s1_bill("x")
    assert upload(c, 9999).status_code == 404


def test_ingest_rejects_oversized_upload(api, monkeypatch):
    c, _, ctx, fakes = api
    from app.api.routers import invoices
    monkeypatch.setattr(invoices, "MAX_UPLOAD_BYTES", 10)
    assert upload(c, ctx.ramesh.id).status_code == 422


def test_confirm_with_corrections_then_dues_include_it(api):
    c, _, ctx, fakes = api
    fakes.docai.result = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-4000", "invoice_date": "20/09/2026"}
    iid = upload(c, ctx.ramesh.id).json()["invoice_id"]
    r = c.post(f"/invoices/{iid}/confirm", params={"merchant_id": ctx.ramesh.id}, json={"corrections": {"grand_total": 18_000}})
    assert r.json()["confirmed"] and r.json()["grand_total"] == 18_000
    assert c.post(f"/invoices/{iid}/confirm", params={"merchant_id": ctx.neha.id}).status_code == 404


def test_confirm_with_bad_field_is_422(api):
    c, _, ctx, fakes = api
    fakes.docai.result = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-4001", "invoice_date": "20/09/2026"}
    iid = upload(c, ctx.ramesh.id).json()["invoice_id"]
    assert c.post(f"/invoices/{iid}/confirm", params={"merchant_id": ctx.ramesh.id}, json={"corrections": {"status": "paid"}}).status_code == 422


def test_s1_full_flow_ask_sharma_and_he_answers(api):
    c, _, ctx, fakes = api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    iid = upload(c, ctx.ramesh.id).json()["invoice_id"]
    q = c.post(f"/invoices/{iid}/ask-supplier", params={"merchant_id": ctx.ramesh.id}).json()
    assert q["status"] == "open"
    ev = c.get(f"/merchants/{ctx.vikas.id}/events").json()
    assert ev == []  # a query is a WhatsApp message, not a soundbox event
    ans = c.post(f"/queries/{q['id']}/answer", json={"answer": "duplicate"}).json()
    assert ans["status"] == "answered" and ans["answer"] == "duplicate"
    assert c.post(f"/queries/{q['id']}/answer", json={"answer": "duplicate"}).status_code == 422


def test_discard_invoice(api):
    c, _, ctx, fakes = api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    iid = upload(c, ctx.ramesh.id).json()["invoice_id"]
    r = c.post(f"/invoices/{iid}/discard", params={"merchant_id": ctx.ramesh.id}).json()
    assert r["status"] == "disputed" and not r["confirmed"]


# ---- IMS
def test_ims_for_composition_merchant_is_409(api):
    c, _, ctx, _ = api
    r = c.get(f"/merchants/{ctx.ramesh.id}/ims", params={"month": "2026-10"})
    assert r.status_code == 409 and r.json()["error"] == "not_applicable"


def test_ims_for_regular_merchant_and_override_and_approve(api):
    c, _, ctx, _ = api
    r = c.get(f"/merchants/{ctx.neha.id}/ims", params={"month": "2026-10"}).json()
    assert r["counts"]["accept"] > 10 and len(r["missing_from_ims"]) == 1
    kp = next(e for e in r["entries"] if e["supplier_name"] == "Kanpur Plastics")
    assert kp["action"] == "pending" and kp["itc_risk"]
    eid = r["entries"][0]["id"]
    assert c.post(f"/merchants/{ctx.neha.id}/ims/{eid}/override", json={"action": "reject"}).json()["action"] == "reject"
    assert c.post(f"/merchants/{ctx.neha.id}/ims/{eid}/override", json={"action": "bogus"}).status_code == 422
    approved = c.post(f"/merchants/{ctx.neha.id}/ims/approve-all", params={"month": "2026-10"}).json()
    assert approved["approved"] > 20 and "GSP" in approved["note"]


# ---- forecast / score / credit
def test_forecast_endpoint_and_bounds(api):
    c, _, ctx, _ = api
    f = c.get(f"/merchants/{ctx.ramesh.id}/forecast").json()
    assert f["shortfall_amount"] == 38_000 and f["first_below_date"] == "2026-11-04"
    assert c.get(f"/merchants/{ctx.ramesh.id}/forecast", params={"days": 0}).status_code == 422
    assert len(c.get(f"/merchants/{ctx.ramesh.id}/forecast", params={"days": 7}).json()["days"]) == 7


def test_score_endpoint(api):
    c, _, ctx, _ = api
    s = c.get(f"/merchants/{ctx.ramesh.id}/score").json()
    assert s["score"] >= 600 and len(s["reasons"]) == 3 and set(s["factors"]) >= {"discipline", "stability"}


def test_s5_consent_offer_accept_and_pay_from_credit(api):
    c, _, ctx, _ = api
    m = ctx.ramesh.id
    no = c.get(f"/merchants/{m}/credit-offer")
    assert no.status_code == 403 and no.json()["error"] == "consent_required"
    assert c.post(f"/merchants/{m}/consents", json={"scope": ["gst_data", "bank_data"]}).status_code == 200
    offer = c.get(f"/merchants/{m}/credit-offer").json()
    assert offer["eligible"] and offer["limit"] == 50_000 and offer["illustrative"] and len(offer["reasons"]) == 3
    assert c.post(f"/merchants/{m}/credit-offer/{offer['offer_id']}/accept").json()["reason"] == "Accepted"
    sid = ctx.ramesh_suppliers["Sharma Traders"].id
    d = c.post("/payments/draft", json={"merchant_id": m, "supplier_id": sid, "amount": 42_300, "source": "credit"}).json()
    p = c.post(f"/payments/{d['id']}/confirm", json={"merchant_id": m}).json()
    assert p["mode"] == "credit_line" and p["amount"] == 42_300


def test_credit_offer_ineligible_returns_reason_not_error(api):
    c, _, ctx, _ = api
    c.post(f"/merchants/{ctx.neha.id}/consents", json={"scope": ["gst_data", "bank_data"]})
    r = c.get(f"/merchants/{ctx.neha.id}/credit-offer").json()
    assert r["eligible"] is False and r["reason"]


# ---- payments
def test_draft_confirm_payment_flow(api):
    c, _, ctx, _ = api
    sid = ctx.ramesh_suppliers["Gupta Oil Mills"].id
    d = c.post("/payments/draft", json={"merchant_id": ctx.ramesh.id, "supplier_id": sid, "amount": 19_800}).json()
    assert d["status"] == "drafted" and d["upi_link"].startswith("upi://pay")
    p = c.post(f"/payments/{d['id']}/confirm", json={"merchant_id": ctx.ramesh.id})
    assert p.status_code == 200 and p.json()["confirmed"]
    assert c.post(f"/payments/{d['id']}/confirm", json={"merchant_id": ctx.ramesh.id}).status_code == 422
    assert c.get(f"/merchants/{ctx.ramesh.id}/dues").json()["total"] == 112_400 - 19_800


def test_draft_validation_errors(api):
    c, _, ctx, _ = api
    sid = ctx.ramesh_suppliers["Gupta Oil Mills"].id
    assert c.post("/payments/draft", json={"merchant_id": ctx.ramesh.id, "supplier_id": sid, "amount": -5}).status_code == 422
    assert c.post("/payments/draft", json={"merchant_id": ctx.ramesh.id, "supplier_id": ctx.neha_suppliers["Kanpur Plastics"].id, "amount": 5}).status_code == 404


def test_cash_log_confirm_cancel(api):
    c, _, ctx, _ = api
    sid = ctx.ramesh_suppliers["Agarwal Dairy"].id
    p = c.post("/payments/cash", json={"merchant_id": ctx.ramesh.id, "supplier_id": sid, "amount": 3000}).json()
    assert p["confirmed"] is False
    assert c.post(f"/payments/cash/{p['id']}/confirm", json={"merchant_id": ctx.ramesh.id}).json()["confirmed"]
    p2 = c.post("/payments/cash", json={"merchant_id": ctx.ramesh.id, "supplier_id": sid, "amount": 100}).json()
    assert c.delete(f"/payments/cash/{p2['id']}", params={"merchant_id": ctx.ramesh.id}).status_code == 204
    assert c.delete(f"/payments/cash/{p2['id']}", params={"merchant_id": ctx.ramesh.id}).status_code == 404


def test_register_csv_download(api):
    c, _, ctx, _ = api
    r = c.get(f"/merchants/{ctx.neha.id}/register.csv", params={"month": "2026-10"})
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("Date,Invoice No")


# ---- agent
def test_chat_runs_tool_and_logs_turn(api):
    c, s, ctx, fakes = api
    fakes.chat.script = [tool_call("get_dues", {"period": "week"}), text("Is hafte 5 suppliers ko ₹1,12,400 dena hai.")]
    r = c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "Is hafte kitna dena hai?", "channel": "whatsapp"}).json()
    assert r["source"] == "llm" and r["tool_calls"][0]["name"] == "get_dues" and r["tool_calls"][0]["result"]["total"] == 112_400
    from sqlmodel import select
    from app.models import Message
    msgs = s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id)).all()
    assert [m.direction for m in msgs] == ["in", "out"] and msgs[1].tool_calls_json[0]["name"] == "get_dues"


def test_chat_uses_merchant_language_default(api):
    c, _, ctx, fakes = api
    fakes.chat.script = [text("Hello.")]
    c.post("/agent/chat", json={"merchant_id": ctx.vikas.id, "text": "hello"})
    assert "Default to English" in fakes.chat.calls[0]["messages"][0]["content"]  # Vikas's language is en


def test_chat_survives_llm_outage_via_router(api):
    c, _, ctx, fakes = api

    def boom(m, t):
        raise RuntimeError("down")
    fakes.chat.script = boom
    r = c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "Paise kab kam padenge?"}).json()
    assert r["source"] == "template" and "38,000" in r["text"]


def test_chat_unknown_merchant(api):
    assert api[0].post("/agent/chat", json={"merchant_id": 9999, "text": "hi"}).status_code == 404


def test_voice_endpoint_returns_transcript_text_and_playable_audio(api):
    c, _, ctx, fakes = api
    fakes.chat.script = [tool_call("get_dues", {"period": "week"}), text("Is hafte 1 lakh 12 hazaar dena hai.")]
    r = c.post("/agent/voice", data={"merchant_id": ctx.ramesh.id}, files={"file": ("a.wav", WAV, "audio/wav")}).json()
    assert r["transcript"] == "Is hafte kitna dena hai?" and r["audio_url"].startswith("http://testserver/media/audio/")
    served = c.get(r["audio_url"].replace("http://testserver", ""))
    assert served.status_code == 200 and served.content == b"RIFFfakewav"


def test_voice_unconvertible_audio_is_422(api, monkeypatch):
    c, _, ctx, _ = api
    monkeypatch.setattr(audio_convert.shutil, "which", lambda _: None)
    r = c.post("/agent/voice", data={"merchant_id": ctx.ramesh.id}, files={"file": ("a.ogg", b"OggS" + b"\x00" * 32, "audio/ogg")})
    assert r.status_code == 422 and "ffmpeg" in r.json()["message"]


def test_bill_images_are_not_publicly_served(api):
    c, _, ctx, fakes = api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    url = upload(c, ctx.ramesh.id).json()["image_url"]
    assert url.startswith("http://testserver/media/bills/")
    assert c.get(url.replace("http://testserver", "")).status_code == 404


def test_soundbox_event_feed_polling(api):
    c, _, ctx, _ = api
    c.post("/demo/simulate-customer-payment", json={"merchant_id": ctx.ramesh.id, "amount": 2500})
    ev = c.get(f"/merchants/{ctx.ramesh.id}/events").json()
    assert len(ev) == 1 and "2,500 prapt hue" in ev[0]["text"]
    assert c.get(f"/merchants/{ctx.ramesh.id}/events", params={"after_id": ev[0]["id"]}).json() == []


# ---- distributor
def test_distributor_endpoints_and_role_guard(api):
    c, _, ctx, _ = api
    rows = c.get(f"/distributors/{ctx.vikas.id}/receivables").json()
    assert len(rows) == 40 and rows[0]["overdue_amount"] >= rows[-1]["overdue_amount"]
    assert c.get(f"/distributors/{ctx.ramesh.id}/receivables").status_code == 404
    one = c.get(f"/distributors/{ctx.vikas.id}/retailers/{ctx.ramesh.id}").json()
    assert one["name"] == "Ramesh General Store" and one["reason_en"]
    assert c.get(f"/distributors/{ctx.vikas.id}/retailers/{ctx.neha.id}").status_code == 404


def test_s6_s10_simulate_payment_shows_on_distributor_dashboard(api):
    c, _, ctx, _ = api
    sim = c.post("/demo/simulate-payment", json={"payer_id": ctx.ramesh.id}).json()
    assert sim["gross"] == 31_500 and sim["mdr"] == 126 and sim["net"] == 31_374
    assert [m["invoice_no"] for m in sim["matched"]] == ["ST-2308", "ST-2309"]
    assert sim["reliability_after"] > sim["reliability_before"]
    top = c.get(f"/distributors/{ctx.vikas.id}/settlements").json()[0]
    assert top["status"] == "matched" and top["payer_name"] == "Ramesh General Store" and top["mdr"] == 126
    assert "31,500 prapt hue" in c.get(f"/merchants/{ctx.vikas.id}/events").json()[0]["text"]


def test_simulate_payment_unknown_distributor_is_404(api):
    c, _, ctx, _ = api
    assert c.post("/demo/simulate-payment", json={"payer_id": ctx.ramesh.id, "supplier_name": "Agarwal Dairy"}).status_code == 404


def test_issue_digital_invoice_lands_in_retailer_ledger(api):
    c, _, ctx, _ = api
    body = {"retailer_id": ctx.ramesh.id, "lines": [{"description": "Tea 250g", "hsn": "0902", "qty": 100, "rate": 120}]}
    r = c.post(f"/distributors/{ctx.vikas.id}/invoices", json=body).json()
    assert r["grand_total"] == 12_600
    assert c.get(f"/merchants/{ctx.ramesh.id}/dues", params={"period": "month"}).json()["total"] > 112_400
    bad = c.post(f"/distributors/{ctx.vikas.id}/invoices", json={"retailer_id": ctx.ramesh.id, "lines": [{"description": "x", "qty": 0, "rate": 1}]})
    assert bad.status_code == 422


def test_reminders_draft_then_send(api):
    c, s, ctx, fakes = api
    fakes.chat.script = lambda m, t: text("no figures here")  # rejected by amount check -> template used
    draft = c.post(f"/distributors/{ctx.vikas.id}/reminders", json={"language": "hi"}).json()
    assert draft["sent"] is False and draft["reminders"] and all("₹" in r["text"] for r in draft["reminders"])
    from sqlmodel import select
    from app.models import Message
    before = len(s.exec(select(Message)).all())
    sent = c.post(f"/distributors/{ctx.vikas.id}/reminders", json={"language": "hi", "send": True, "retailer_ids": [draft["reminders"][0]["retailer_id"]]}).json()
    assert sent["sent"] is True and len(sent["reminders"]) == 1
    assert len(s.exec(select(Message)).all()) == before + 1


# ---- demo
def test_demo_reset_restores_seed_state(api):
    c, _, ctx, _ = api
    c.post("/demo/simulate-payment", json={"payer_id": ctx.ramesh.id})
    assert c.post("/demo/reset").json() == {"ok": True}
    from sqlmodel import select
    from app.models import Merchant
    first = c.get("/merchants").json()[0]["id"]
    assert c.get(f"/merchants/{first}/dues").json()["total"] == 112_400


# ---- contract
def test_openapi_contract_lists_key_endpoints(api):
    paths = api[0].get("/openapi.json").json()["paths"]
    for p in ("/invoices/ingest", "/agent/voice", "/agent/chat", "/payments/draft", "/demo/simulate-payment",
              "/distributors/{distributor_id}/settlements", "/merchants/{merchant_id}/forecast"):
        assert p in paths


# ---- CORS (the web dashboard calls the API from another origin)
def test_cors_preflight_allows_the_dashboard_origin(api):
    c = api[0]
    r = c.options("/merchants", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_does_not_allow_other_origins(api):
    c = api[0]
    r = c.get("/merchants", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
