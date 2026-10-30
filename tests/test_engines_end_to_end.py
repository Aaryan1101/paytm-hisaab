"""Both agent engines, driven through the public HTTP API and the WhatsApp dispatcher."""
import io

from PIL import Image
from sqlmodel import select

from app.ai.agent import Agent
from app.ai.graph.agent_graph import GraphAgent
from app.channels.whatsapp.dispatcher import InboundDispatcher
from app.channels.whatsapp.payload import InboundMessage
from app.container import Container
from app.models import Message, PaymentOut
from tests.fakes import FakeWhatsApp, s1_bill, text, tool_call

IMG = io.BytesIO()
Image.new("RGB", (500, 300), (220, 210, 200)).save(IMG, "JPEG")
PHOTO = IMG.getvalue()
WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64


def test_container_builds_the_requested_engine(tmp_path):
    from app.storage import MediaStore
    from tests.fakes import FakeChat, FakeDocAI, FakeStt, FakeTts
    mk = lambda e: Container(FakeChat([]), FakeDocAI({}), FakeStt(), FakeTts(), MediaStore(str(tmp_path), "http://x"), agent_engine=e)
    assert isinstance(mk("native").agent, Agent) and isinstance(mk("graph").agent, GraphAgent)
    assert mk("graph").confirmations is not None and mk("native").checkpointer is not None


def test_chat_api_answers_with_a_tool_and_returns_a_trace(engine_api):
    c, s, ctx, fakes = engine_api
    fakes.chat.script = [tool_call("get_dues", {"period": "week"}), text("Is hafte 5 suppliers ko ₹1,12,400 dena hai.")]
    r = c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "Is hafte kitna dena hai?"}).json()
    assert r["source"] == "llm" and r["tool_calls"][0]["result"]["total"] == 112_400
    assert r["trace"]["engine"] == fakes.engine and r["trace"]["source"] == "llm"
    assert [x["kind"] for x in r["trace"]["steps"]] == ["llm", "tool", "llm"]


def test_trace_is_stored_with_the_reply_message(engine_api):
    c, s, ctx, fakes = engine_api
    fakes.chat.script = [tool_call("get_dues", {"period": "week"}), text("Is hafte ₹1,12,400 dena hai.")]
    c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "Is hafte kitna dena hai?"})
    reply = s.exec(select(Message).where(Message.merchant_id == ctx.ramesh.id, Message.direction == "out")).all()[-1]
    assert reply.trace_json["engine"] == fakes.engine and reply.trace_json["total_ms"] >= 0 and reply.tool_calls_json[0]["name"] == "get_dues"


def test_voice_api_stores_trace(engine_api):
    c, s, ctx, fakes = engine_api
    fakes.chat.script = [tool_call("get_dues", {"period": "week"}), text("Is hafte 1 lakh 12 hazaar dena hai.")]
    r = c.post("/agent/voice", data={"merchant_id": ctx.ramesh.id}, files={"file": ("a.wav", WAV, "audio/wav")})
    assert r.status_code == 200
    out = s.exec(select(Message).where(Message.channel == "soundbox", Message.direction == "out")).all()[-1]
    assert out.trace_json["engine"] == fakes.engine


def test_chat_memory_across_requests_only_for_the_graph_engine(engine_api):
    c, s, ctx, fakes = engine_api
    fakes.chat.script = lambda m, t: text("ok")
    c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "pehla sawaal", "channel": "app"})
    c.post("/agent/chat", json={"merchant_id": ctx.ramesh.id, "text": "doosra sawaal", "channel": "app"})
    users = [m["content"] for m in fakes.chat.calls[1]["messages"] if m["role"] == "user"]
    assert users == (["pehla sawaal", "doosra sawaal"] if fakes.engine == "graph" else ["doosra sawaal"])


def dispatcher(engine_api, media=b"", mime="image/jpeg"):
    c, s, ctx, fakes = engine_api
    wa = FakeWhatsApp(media, mime)
    container = Container(fakes.chat, fakes.docai, fakes.stt, fakes.tts, fakes.container.media, whatsapp=wa,
                          agent_engine=fakes.engine, checkpointer=fakes.container.checkpointer)
    return InboundDispatcher(s, container, wa), wa


def msg(kind="text", **kw):
    return InboundMessage(message_id=kw.pop("message_id", "m"), from_phone="919810000001", kind=kind, **kw)


def test_s1_whatsapp_flow_duplicate_card_then_tap_resumes_the_confirmation(engine_api):
    c, s, ctx, fakes = engine_api
    fakes.docai.result = s1_bill(ctx.vikas.gstin)
    d, wa = dispatcher(engine_api, PHOTO)
    d.handle(msg("image", media_id="i"))
    buttons = wa.buttons[0][2]
    d.handle(msg("button", button_id=buttons[2].id, message_id="t1"))  # "Sharma se poochho"
    assert "Supplier ko message bhej diya" in wa.all_text()
    assert "sawaal poocha hai" in s.exec(select(Message).where(Message.merchant_id == ctx.vikas.id)).all()[-1].text
    d.handle(msg("button", button_id=buttons[2].id, message_id="t2"))  # double tap
    assert "pehle hi ho chuka hai" in wa.all_text()


def test_s9_whatsapp_cash_flow_confirm_via_graph_thread(engine_api):
    c, s, ctx, fakes = engine_api
    fakes.chat.script = [tool_call("log_cash_payment", {"supplier": "Agarwal dairy", "amount": 3000}),
                         text("Agarwal Dairy ko ₹3,000 cash likh liya. Confirm karein?")]
    d, wa = dispatcher(engine_api)
    d.handle(msg(text="Agarwal dairy ko teen hazaar cash diye"))
    to, body, buttons = wa.buttons[0]
    assert "3,000" in body and [b.title for b in buttons] == ["Haan, sahi hai", "Nahi"]
    pending = s.exec(select(PaymentOut).where(PaymentOut.confirmed == False)).one()  # noqa: E712
    d.handle(msg("button", button_id=buttons[0].id, message_id="tap"))
    assert s.get(PaymentOut, pending.id).confirmed is True


def test_whatsapp_text_trace_is_logged(engine_api):
    c, s, ctx, fakes = engine_api
    fakes.chat.script = lambda m, t: text("Namaste!")
    d, wa = dispatcher(engine_api)
    d.handle(msg(text="namaste"))
    out = s.exec(select(Message).where(Message.channel == "whatsapp", Message.direction == "out")).all()[-1]
    assert out.trace_json["engine"] == fakes.engine


def test_build_container_falls_back_to_memory_when_postgres_is_down(monkeypatch, tmp_path):
    from app import container as container_module
    from app.config import Settings

    def down(_url):
        raise ConnectionError("postgres unreachable")
    monkeypatch.setattr(container_module, "postgres_checkpointer", down)
    c = container_module.build_container(Settings(agent_engine="graph", sarvam_api_key="k", media_dir=str(tmp_path),
                                                  sarvam_cache_dir=str(tmp_path / "c")))
    assert isinstance(c.agent, GraphAgent) and c.checkpointer is not None
