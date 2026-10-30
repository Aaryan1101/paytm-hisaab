"""Golden tests: the ten planted demo scenarios (S1-S10) exercised through the public HTTP API."""
import io
import json

from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.bootstrap import ensure_seeded
from app.models import Merchant, PaymentOut
from tests.fakes import s1_bill, text, tool_call

IMG = io.BytesIO()
Image.new("RGB", (500, 300), (220, 210, 200)).save(IMG, "JPEG")
PHOTO = IMG.getvalue()
WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64


def upload(c, mid):
    return c.post("/invoices/ingest", data={"merchant_id": mid}, files={"file": ("b.jpg", PHOTO, "image/jpeg")}).json()


# ---- bootstrap
def test_ensure_seeded_seeds_empty_db_once():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert ensure_seeded(engine) is True
    assert ensure_seeded(engine) is False
    with Session(engine) as s:
        assert len(s.exec(select(Merchant)).all()) == 42


def test_openapi_export_script(tmp_path, monkeypatch):
    from scripts import export_openapi
    monkeypatch.setattr(export_openapi, "OUT", tmp_path / "shared" / "openapi.json")
    export_openapi.main()
    assert "/agent/voice" in json.loads((tmp_path / "shared" / "openapi.json").read_text())["paths"]


# ---- S1..S10
def test_s1_duplicate_bill_caught_and_sharma_asked(api):
    c, _, ctx, fakes = api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    r = upload(c, ctx.ramesh.id)
    assert r["duplicate"]["paid_on"] == "2026-10-12"
    q = c.post(f"/invoices/{r['invoice_id']}/ask-supplier", params={"merchant_id": ctx.ramesh.id}).json()
    assert q["status"] == "open"


def test_s2_missing_credit_note_alert_and_one_tap_request(api):
    c, _, ctx, fakes = api
    [alert] = c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "missing_credit_note"}).json()
    assert "2,300" in alert["message_en"] and alert["invoice_id"]
    fakes.chat.script = [tool_call("request_credit_note", {"invoice_id": alert["invoice_id"], "amount": 2300}), text("Credit note maang liya.")]
    r = c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "credit note maango"}).json()
    assert r["tool_calls"][0]["result"]["status"] == "requested"


def test_s3_wrong_gst_rate_flagged_with_expected_rate(api):
    c, _, ctx, fakes = api
    fakes.docai.result = {"supplier_name": "Gupta Oil Mills", "supplier_gstin": ctx.ramesh_suppliers["Gupta Oil Mills"].gstin,
                          "invoice_no": "GO-8000", "invoice_date": "30/10/2026", "taxable_total": 1000, "tax_total": 180, "grand_total": 1180,
                          "line_items": [{"description": "Mustard Oil", "hsn": "1514", "qty": 10, "rate": 100, "taxable_value": 1000,
                                          "gst_rate": 18, "cgst": 90, "sgst": 90}]}
    issue = next(i for i in upload(c, ctx.ramesh.id)["issues"] if i["code"] == "hsn_rate_mismatch")
    assert issue["line_index"] == 0 and "5%" in issue["message_en"]


def test_s4_cancelled_supplier_gstin_flagged_in_ims(api):
    c, _, ctx, _ = api
    ims = c.get(f"/merchants/{ctx.neha.id}/ims", params={"month": "2026-10"}).json()
    kp = next(e for e in ims["entries"] if e["supplier_name"] == "Kanpur Plastics")
    assert kp["action"] == "pending" and kp["itc_risk"]
    assert any("cancelled" in a["message_en"] for a in c.get(f"/merchants/{ctx.neha.id}/alerts", params={"type": "gstin_risk"}).json())


def test_s5_voice_question_to_shortfall_to_credit_offer(api):
    c, _, ctx, fakes = api
    fakes.stt.transcript = "Paise kab kam padenge?"
    fakes.chat.script = [tool_call("forecast_cash", {}), text("Thursday ko 38 hazaar rupaye kam pad sakte hain. Credit option dekhna chahenge?")]
    v = c.post("/agent/voice", data={"merchant_id": ctx.ramesh.id}, files={"file": ("a.wav", WAV, "audio/wav")}).json()
    assert v["tool_calls"][0]["result"]["shortfall_amount"] == 38_000 and v["audio_url"]
    m = ctx.ramesh.id
    c.post(f"/merchants/{m}/consents", json={"scope": ["gst_data", "bank_data"]})
    assert c.get(f"/merchants/{m}/credit-offer").json()["limit"] == 50_000


def test_s6_one_payment_clears_two_invoices_mdr_separate(api):
    c, _, ctx, _ = api
    sim = c.post("/demo/simulate-payment", json={"payer_id": ctx.ramesh.id}).json()
    assert [m["invoice_no"] for m in sim["matched"]] == ["ST-2308", "ST-2309"] and sim["gross"] - sim["mdr"] == sim["net"]


def test_s7_unknown_payee_fuzzy_matched_then_confirmed_once(api):
    c, _, ctx, _ = api
    [a] = c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "confirm_payee"}).json()
    assert a["supplier_id"] == ctx.ramesh_suppliers["Sharma Traders"].id
    assert c.post(f"/merchants/{ctx.ramesh.id}/payments/{a['payment_id']}/confirm-payee", json={"supplier_id": a["supplier_id"]}).status_code == 200
    assert c.get(f"/merchants/{ctx.ramesh.id}/alerts", params={"type": "confirm_payee"}).json() == []


def test_s8_handwritten_kachcha_bill_tagged_non_gst(api):
    c, _, ctx, fakes = api
    fakes.docai.result = {"supplier_name": "Agarwal Dairy", "is_handwritten": True, "invoice_date": "30/10/2026", "grand_total": 3450,
                          "line_items": [{"description": "Doodh 60L", "taxable_value": 3450}]}
    r = upload(c, ctx.ramesh.id)
    assert r["invoice"]["bill_type"] == "kachcha" and "grand_total" in r["low_confidence_fields"]
    iid = r["invoice_id"]
    assert c.post(f"/invoices/{iid}/confirm", params={"merchant_id": ctx.ramesh.id}).json()["confirmed"]


def test_s9_cash_voice_note_logged_only_after_confirmation(api):
    c, s, ctx, fakes = api
    fakes.stt.transcript = "Agarwal dairy ko teen hazaar cash diye"
    fakes.container.agent._router_first = True
    fakes.chat.script = [text("Agarwal Dairy ko ₹3,000 cash likh liya. Confirm karein?")]
    v = c.post("/agent/voice", data={"merchant_id": ctx.ramesh.id}, files={"file": ("a.wav", WAV, "audio/wav")}).json()
    pending = v["tool_calls"][0]["result"]
    assert pending["amount"] == 3000 and pending["status"] == "needs_confirmation"
    assert s.get(PaymentOut, pending["pending_payment_id"]).confirmed is False
    assert c.post(f"/payments/cash/{pending['pending_payment_id']}/confirm", json={"merchant_id": ctx.ramesh.id}).json()["confirmed"]


def test_s10_live_payment_lands_matched_with_announcement(api):
    c, _, ctx, _ = api
    c.post("/demo/simulate-payment", json={"payer_id": ctx.ramesh.id})
    top = c.get(f"/distributors/{ctx.vikas.id}/settlements").json()[0]
    assert top["status"] == "matched" and top["mdr"] > 0
    assert "prapt hue" in c.get(f"/merchants/{ctx.vikas.id}/events").json()[0]["text"]
    assert c.post("/demo/reset").status_code == 200
    assert c.get(f"/merchants/{ctx.vikas.id}/events").json() == []
