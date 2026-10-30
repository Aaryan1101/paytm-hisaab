import hashlib
import hmac
import io
import json
from datetime import date

import httpx
import pytest
from PIL import Image
from sqlmodel import select

from app.ai.agent import Agent, ToolTrace
from app.channels.base import Button
from app.ai.graph import pending as pending_actions
from app.channels.whatsapp import bill_cards, button_actions, signature
from app.channels.whatsapp.client import WhatsAppClient, WhatsAppError, to_wa_number
from app.channels.whatsapp.dispatcher import InboundDispatcher
from app.channels.whatsapp.notifier import WhatsAppNotifier
from app.channels.whatsapp.payload import InboundMessage, parse_webhook
from app.config import settings
from app.container import Container
from app.models import InvoiceRow, Message, PaymentOut
from app.storage import MediaStore
from tests.fakes import FakeChat, FakeDocAI, FakeStt, FakeTts, FakeWhatsApp, s1_bill, text, tool_call

IMG = io.BytesIO()
Image.new("RGB", (500, 300), (220, 210, 200)).save(IMG, "JPEG")
PHOTO = IMG.getvalue()
WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64


# ---- signature
def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature():
    assert signature.verify("s3cret", b'{"a":1}', sign("s3cret", b'{"a":1}'))


@pytest.mark.parametrize("secret,header", [("s3cret", "sha256=deadbeef"), ("s3cret", None), ("s3cret", "md5=abc"), ("", "sha256=x"), ("", None)])
def test_bad_or_missing_signature_rejected(secret, header):
    assert not signature.verify(secret, b"body", header)


def test_tampered_body_rejected():
    assert not signature.verify("s3cret", b"tampered", sign("s3cret", b"original"))


# ---- payload
def wrap(*messages) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": list(messages)}}]}]}


def test_parse_text_image_audio_document():
    out = parse_webhook(wrap(
        {"from": "919810000001", "id": "m1", "type": "text", "text": {"body": "Is hafte kitna dena hai?"}},
        {"from": "919810000001", "id": "m2", "type": "image", "image": {"id": "img1", "mime_type": "image/jpeg", "caption": "bill"}},
        {"from": "919810000001", "id": "m3", "type": "audio", "audio": {"id": "aud1", "mime_type": "audio/ogg"}},
        {"from": "919810000001", "id": "m4", "type": "document", "document": {"id": "doc1", "mime_type": "application/pdf"}}))
    assert [(m.kind, m.media_id) for m in out] == [("text", None), ("image", "img1"), ("audio", "aud1"), ("document", "doc1")]
    assert out[0].text == "Is hafte kitna dena hai?" and out[1].text == "bill" and out[3].mime_type == "application/pdf"


def test_parse_button_and_list_replies():
    out = parse_webhook(wrap(
        {"from": "1", "id": "a", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "dup:5:ask", "title": "Sharma se poochho"}}},
        {"from": "1", "id": "b", "type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": "x:1:y", "title": "T"}}}))
    assert [(m.kind, m.button_id) for m in out] == [("button", "dup:5:ask"), ("button", "x:1:y")]


def test_status_callbacks_and_unknown_types_ignored():
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "s", "status": "delivered"}]}}]}]}
    assert parse_webhook(payload) == []
    assert parse_webhook(wrap({"from": "1", "id": "x", "type": "sticker"})) == []
    assert parse_webhook({}) == [] and parse_webhook({"entry": [{"changes": [{}]}]}) == []


# ---- client (httpx mock transport)
def make_client(handler):
    return WhatsAppClient("TOKEN", "PHONEID", httpx.Client(transport=httpx.MockTransport(handler)))


def test_send_text_payload_and_auth():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["json"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json={})
    make_client(handler).send_text("919810000001", "namaste")
    assert seen["url"].endswith("/PHONEID/messages") and seen["auth"] == "Bearer TOKEN"
    assert seen["json"] == {"messaging_product": "whatsapp", "to": "919810000001", "type": "text", "text": {"body": "namaste"}}


def test_buttons_truncated_to_whatsapp_limits():
    seen = {}

    def handler(req):
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json={})
    buttons = [Button(f"b{i}", "x" * 40) for i in range(5)]
    make_client(handler).send_buttons("91", "y" * 2000, buttons)
    inter = seen["json"]["interactive"]
    assert len(inter["action"]["buttons"]) == 3 and len(inter["action"]["buttons"][0]["reply"]["title"]) == 20 and len(inter["body"]["text"]) == 1024


def test_empty_buttons_falls_back_to_plain_text():
    seen = {}
    make_client(lambda req: (seen.update(j=json.loads(req.content)), httpx.Response(200, json={}))[1]).send_buttons("91", "hi", [])
    assert seen["j"]["type"] == "text"


def test_send_error_raises():
    with pytest.raises(WhatsAppError, match="400"):
        make_client(lambda req: httpx.Response(400, text="bad")).send_text("91", "x")


def test_download_media_is_two_step_with_auth_on_both():
    calls = []

    def handler(req):
        calls.append((str(req.url), req.headers["authorization"]))
        if str(req.url).endswith("/MEDIA1"):
            return httpx.Response(200, json={"url": "https://cdn.example/f", "mime_type": "audio/ogg"})
        return httpx.Response(200, content=b"BYTES")
    data, mime = make_client(handler).download_media("MEDIA1")
    assert data == b"BYTES" and mime == "audio/ogg" and all(a == "Bearer TOKEN" for _, a in calls) and len(calls) == 2


def test_download_failures_raise():
    with pytest.raises(WhatsAppError):
        make_client(lambda req: httpx.Response(404)).download_media("X")


def test_upload_media_returns_id():
    assert make_client(lambda req: httpx.Response(200, json={"id": "UP1"})).upload_media(b"x", "audio/ogg") == "UP1"
    with pytest.raises(WhatsAppError):
        make_client(lambda req: httpx.Response(500)).upload_media(b"x", "audio/ogg")


@pytest.mark.parametrize("phone,expected", [("9810000001", "919810000001"), ("+91 98100 00001", "919810000001"), ("919810000001", "919810000001")])
def test_to_wa_number(phone, expected):
    assert to_wa_number(phone) == expected


# ---- notifier
def test_notifier_sends_and_logs(seeded):
    s, ctx = seeded
    wa = FakeWhatsApp()
    WhatsAppNotifier(wa, s).send(ctx.ramesh.id, "hello", [Button("a", "Haan")])
    assert wa.buttons[0][0] == "919810000001" and wa.buttons[0][1] == "hello"
    assert "[Haan]" in s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id)).all()[-1].text


def test_notifier_delivery_failure_is_swallowed(seeded):
    s, ctx = seeded

    class Broken(FakeWhatsApp):
        def send_buttons(self, *a):
            raise WhatsAppError("down")
    WhatsAppNotifier(Broken(), s).send(ctx.ramesh.id, "hello")  # must not raise
    assert s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id)).all()


# ---- bill cards
def ingest_result(api_fixture, raw):
    c, s, ctx, fakes = api_fixture
    from app.ai.extract import InvoiceExtractor
    from app.services import ingest_service
    return ingest_service.ingest_invoice(s, ctx.ramesh.id, PHOTO, "whatsapp", InvoiceExtractor(FakeDocAI(raw)))


def test_s1_duplicate_card_matches_spec(api):
    _, _, ctx, _ = api
    r = ingest_result(api, s1_bill(ctx.vikas.gstin))
    body, buttons = bill_cards.render(r)
    assert "Bill padh liya ✅" in body and "Sharma Traders · Inv #ST-2291 · 28 Oct" in body and "₹18,640 (GST ₹888)" in body
    assert "Due: 4 Nov" in body
    assert "⚠️ Yeh bill #ST-2291 pehle 12 Oct ko bhi aaya tha aur aapne ₹18,640 pay kar diya hai. Duplicate lag raha hai." in body
    assert buttons.kind == "dup" and buttons.ref_id == r.invoice_id
    assert [o.title for o in buttons.options] == ["Duplicate hai", "Naya bill hai", "Sharma se poochho"]
    assert [o.choice for o in buttons.options] == ["ignore", "new", "ask"] and all(len(o.title) <= 20 for o in buttons.options)


def test_clean_bill_card_has_confirm_buttons(api):
    _, _, ctx, _ = api
    r = ingest_result(api, {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-5000", "invoice_date": "20/09/2026"})
    body, buttons = bill_cards.render(r)
    assert "⚠️" not in body and buttons.kind == "bill" and [o.choice for o in buttons.options] == ["ok", "no"]


def test_bill_with_issue_lists_it_and_kachcha_is_tagged(api):
    _, _, ctx, _ = api
    r = ingest_result(api, {**s1_bill(ctx.vikas.gstin[:-1] + "0"), "invoice_no": "ST-5001", "invoice_date": "20/09/2026"})
    assert "GSTIN galat lagta hai" in bill_cards.render(r)[0]
    k = ingest_result(api, {"supplier_name": "Agarwal Dairy", "is_handwritten": True, "invoice_date": "30/10/2026",
                            "grand_total": 3450, "line_items": [{"description": "Milk", "taxable_value": 3450}]})
    body, _ = bill_cards.render(k)
    assert "kachcha bill (non-GST)" in body and "Total ₹3,450 sahi hai?" in body


# ---- pending actions derived from what the agent prepared
def test_pending_from_traces():
    cash = ToolTrace("log_cash_payment", {}, {"pending_payment_id": 7})
    draft = ToolTrace("draft_payment", {}, {"draft_id": 9})
    p = pending_actions.from_traces([cash])
    assert (p.kind, p.ref_id, [o.choice for o in p.options]) == ("cash", 7, ["ok", "no"])
    p = pending_actions.from_traces([draft])
    assert (p.kind, p.ref_id, [o.title for o in p.options]) == ("pay", 9, ["Pay karein", "Cancel"])
    assert pending_actions.from_traces([ToolTrace("get_dues", {}, {})]) is None
    assert pending_actions.from_traces([ToolTrace("draft_payment", {}, {"error": "invalid"})]) is None


# ---- button actions
def tap(api, merchant, button_id):
    from app.channels.db_notifier import DbNotifier
    _, s, _, _ = api
    return button_actions.handle(s, DbNotifier(s), merchant.id, button_id)


def test_bill_ok_confirms_and_no_discards(api):
    _, s, ctx, _ = api
    r = ingest_result(api, {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-5002", "invoice_date": "20/09/2026"})
    assert "ledger mein jod diya" in tap(api, ctx.ramesh, f"bill:{r.invoice_id}:ok")
    assert s.get(InvoiceRow, r.invoice_id).confirmed
    r2 = ingest_result(api, {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-5003", "invoice_date": "20/09/2026"})
    assert "hata diya" in tap(api, ctx.ramesh, f"bill:{r2.invoice_id}:no") and s.get(InvoiceRow, r2.invoice_id).status == "disputed"


def test_s1_ask_supplier_then_distributor_answers_via_buttons(api):
    _, s, ctx, _ = api
    r = ingest_result(api, s1_bill(ctx.vikas.gstin))
    assert "Supplier ko message bhej diya" in tap(api, ctx.ramesh, f"dup:{r.invoice_id}:ask")
    msg = s.exec(select(Message).where(Message.merchant_id == ctx.vikas.id)).all()[-1].text
    assert "Ramesh General Store ne bill #ST-2291 par sawaal poocha hai" in msg and "Duplicate hai" in msg
    from app.models import SupplierQuery
    q = s.exec(select(SupplierQuery)).one()
    assert "Jawab bhej diya" in tap(api, ctx.vikas, f"qa:{q.id}:duplicate")
    assert "duplicate hai" in s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id)).all()[-1].text
    assert s.get(InvoiceRow, r.invoice_id).status == "disputed"


def test_cash_and_payment_buttons(api):
    _, s, ctx, _ = api
    from app.services import payment_service
    from app import clock
    cash = payment_service.log_cash_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Agarwal Dairy"].id, 3000, clock.now())
    assert "pakka kar diya" in tap(api, ctx.ramesh, f"cash:{cash.id}:ok") and s.get(PaymentOut, cash.id).confirmed
    cash2 = payment_service.log_cash_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Agarwal Dairy"].id, 100, clock.now())
    assert "hata di" in tap(api, ctx.ramesh, f"cash:{cash2.id}:no") and s.get(PaymentOut, cash2.id) is None
    d = payment_service.draft_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Gupta Oil Mills"].id, 19_800, "bank")
    assert "₹19,800 ka payment ho gaya" in tap(api, ctx.ramesh, f"pay:{d.id}:ok")
    d2 = payment_service.draft_payment(s, ctx.ramesh.id, ctx.ramesh_suppliers["Gupta Oil Mills"].id, 5, "bank")
    assert "cancel" in tap(api, ctx.ramesh, f"pay:{d2.id}:no")


@pytest.mark.parametrize("bad", ["", "garbage", "bill:x:ok", "bill:1", "nope:1:ok", "bill:1:ok:extra"])
def test_malformed_buttons_are_polite(api, bad):
    assert "samajh nahi aaya" in tap(api, api[2].ramesh, bad)


def test_button_for_someone_elses_object_reports_error(api):
    _, s, ctx, _ = api
    r = ingest_result(api, s1_bill(ctx.vikas.gstin))
    assert tap(api, ctx.neha, f"bill:{r.invoice_id}:ok").startswith("Nahi ho paya")


# ---- dispatcher
def dispatcher(api, media=b"", mime="image/jpeg", chat=None, wa=None):
    c, s, ctx, fakes = api
    wa = wa or FakeWhatsApp(media, mime)
    if chat is not None:
        fakes.chat.script = chat
    container = Container(fakes.chat, fakes.docai, fakes.stt, fakes.tts, fakes.container.media, whatsapp=wa)
    return InboundDispatcher(s, container, wa), wa


def msg(kind="text", phone="919810000001", **kw):
    return InboundMessage(message_id=kw.pop("message_id", "m"), from_phone=phone, kind=kind, **kw)


def test_text_goes_to_agent_and_reply_is_sent(api):
    _, _, ctx, fakes = api
    d, wa = dispatcher(api, chat=[tool_call("get_dues", {"period": "week"}), text("Is hafte 5 suppliers ko ₹1,12,400 dena hai.")])
    d.handle(msg(text="Is hafte kitna dena hai?"))
    assert "₹1,12,400" in wa.all_text() and wa.buttons == [] or "₹1,12,400" in wa.all_text()


def test_unregistered_number_is_told_so(api):
    d, wa = dispatcher(api)
    d.handle(msg(phone="911111111111", text="hi"))
    assert wa.texts == [("911111111111", "Yeh number Hisaab par registered nahi hai.")]


def test_s1_bill_photo_replies_with_duplicate_card_and_buttons(api):
    _, s, ctx, fakes = api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    d, wa = dispatcher(api, media=PHOTO)
    d.handle(msg("image", media_id="img1"))
    to, body, buttons = wa.buttons[0]
    assert to == "919810000001" and "Duplicate lag raha hai" in body and len(buttons) == 3
    assert all(b.id.startswith("g:c-") for b in buttons) and [b.id.split(":")[2] for b in buttons] == ["ignore", "new", "ask"]


def test_unreadable_bill_replies_with_the_reason(api):
    _, _, ctx, fakes = api
    fakes.docai.result = {"supplier_name": "X"}
    d, wa = dispatcher(api, media=PHOTO)
    d.handle(msg("image", media_id="img1"))
    assert "Could not read the bill" in wa.all_text()


def test_pdf_document_is_ingested_too(api):
    _, _, ctx, fakes = api
    fakes.docai.result = {**s1_bill(ctx.vikas.gstin), "invoice_no": "ST-6000", "invoice_date": "20/09/2026"}
    d, wa = dispatcher(api, media=b"%PDF-1.4 fake", mime="application/pdf")
    d.handle(msg("document", media_id="doc1"))
    assert fakes.docai.calls[-1]["content_type"] == "application/pdf" and "Bill padh liya" in wa.all_text()


def test_s9_voice_note_cash_flow_asks_for_confirmation(api):
    _, s, ctx, fakes = api
    fakes.stt.transcript = "Agarwal dairy ko teen hazaar cash diye"
    fakes.container.router_first = True
    d, wa = dispatcher(api, media=WAV, mime="audio/ogg", chat=[text("Agarwal Dairy ko ₹3,000 cash likh liya. Confirm karein?")])
    d._c.agent = Agent(fakes.chat, router_first=True)
    d._c.voice._agent = d._c.agent
    d.handle(msg("audio", media_id="aud1"))
    to, body, buttons = wa.buttons[0]
    assert [b.title for b in buttons] == ["Haan, sahi hai", "Nahi"] and "cash" in body
    pending = s.exec(select(PaymentOut).where(PaymentOut.confirmed == False)).one()  # noqa: E712
    assert pending.amount == 3000 and buttons[0].id.startswith("g:c-") and buttons[0].id.endswith(":ok")
    d.handle(msg("button", button_id=buttons[0].id, message_id="tap1"))
    assert s.get(PaymentOut, pending.id).confirmed and "cash payment pakka kar diya" in wa.all_text()


def test_voice_note_reply_failure_does_not_lose_text(api):
    _, _, ctx, fakes = api
    fakes.stt.transcript = "namaste"
    d, wa = dispatcher(api, media=WAV, mime="audio/ogg", chat=[text("Namaste.")])
    d.handle(msg("audio", media_id="aud1"))  # ffmpeg missing in test env -> voice note skipped, text still sent
    assert "Namaste." in wa.all_text()


def test_button_tap_replies_with_result(api):
    _, _, ctx, fakes = api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    d, wa = dispatcher(api, media=PHOTO)
    d.handle(msg("image", media_id="i"))
    d.handle(msg("button", button_id=wa.buttons[0][2][0].id, message_id="m2"))
    assert "Bill hata diya." in wa.all_text()


def test_unexpected_error_sends_try_again_not_a_crash(api):
    _, _, ctx, fakes = api

    def boom(messages, tools):
        raise RuntimeError("everything is down")
    d, wa = dispatcher(api)
    d._c.agent = type("A", (), {"respond": staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))})()
    d.handle(msg(text="hello"))
    assert "dobara bhejein" in wa.all_text()


def test_conversation_history_gives_followups_context(api):
    _, s, ctx, fakes = api
    d, wa = dispatcher(api, chat=[text("Namaste! Sharma ka kuch baaki hai, pay karein?"), text("Theek hai.")])
    d.handle(msg(text="namaste", message_id="a"))
    d.handle(msg(text="haan", message_id="b"))
    turns = [m["content"] for m in fakes.chat.calls[1]["messages"] if m["role"] in ("user", "assistant")]
    assert turns == ["namaste", "Namaste! Sharma ka kuch baaki hai, pay karein?", "haan"]


# ---- webhook endpoint
def post_signed(client, payload, secret="s3cret", signature_override=None):
    body = json.dumps(payload).encode()
    return client.post("/webhooks/whatsapp", content=body,
                       headers={"X-Hub-Signature-256": signature_override or sign(secret, body), "Content-Type": "application/json"})


@pytest.fixture
def wa_api(api, monkeypatch):
    c, s, ctx, fakes = api
    monkeypatch.setattr(settings, "whatsapp_app_secret", "s3cret")
    monkeypatch.setattr(settings, "whatsapp_verify_token", "verify-me")
    wa = FakeWhatsApp(PHOTO)
    fakes.container.whatsapp = wa
    c.app.state.session_factory = lambda: _NoCloseSession(s)
    from app.api.routers import webhooks
    webhooks._SEEN.clear()
    return c, s, ctx, fakes, wa


class _NoCloseSession:
    """Lets the webhook's background task reuse the test session without closing it."""

    def __init__(self, s):
        self.s = s

    def __enter__(self):
        return self.s

    def __exit__(self, *a):
        return False


def test_webhook_verification_handshake(wa_api):
    c = wa_api[0]
    ok = c.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    assert c.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"}).status_code == 403


def test_webhook_rejects_bad_signature(wa_api):
    c = wa_api[0]
    assert post_signed(c, wrap({"from": "1", "id": "x", "type": "text", "text": {"body": "hi"}}), signature_override="sha256=bad").status_code == 403


def test_webhook_rejects_everything_when_secret_unset(wa_api, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_app_secret", "")
    assert post_signed(wa_api[0], wrap(), secret="").status_code == 403


def test_webhook_503_when_whatsapp_not_configured(wa_api):
    c, _, _, fakes, _ = wa_api
    fakes.container.whatsapp = None
    assert post_signed(c, wrap()).status_code == 503


def test_webhook_invalid_json_is_400(wa_api):
    c = wa_api[0]
    body = b"{not json"
    r = c.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": sign("s3cret", body)})
    assert r.status_code == 400


def test_webhook_processes_message_and_replies(wa_api):
    c, s, ctx, fakes, wa = wa_api
    fakes.chat.script = [tool_call("get_dues", {"period": "week"}), text("Is hafte 5 suppliers ko ₹1,12,400 dena hai.")]
    r = post_signed(c, wrap({"from": "919810000001", "id": "wamid.1", "type": "text", "text": {"body": "Is hafte kitna dena hai?"}}))
    assert r.status_code == 200 and r.json() == {"received": 1}
    assert "₹1,12,400" in wa.all_text()


def test_webhook_ignores_redelivered_message(wa_api):
    c, _, _, fakes, wa = wa_api
    fakes.chat.script = lambda m, t: text("Namaste.")
    payload = wrap({"from": "919810000001", "id": "wamid.dup", "type": "text", "text": {"body": "namaste"}})
    post_signed(c, payload)
    post_signed(c, payload)
    assert wa.all_text().count("Namaste.") == 1


def test_webhook_status_only_payload_is_fine(wa_api):
    c = wa_api[0]
    r = post_signed(c, {"entry": [{"changes": [{"value": {"statuses": [{"id": "s"}]}}]}]})
    assert r.status_code == 200 and r.json() == {"received": 0}
