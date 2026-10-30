"""The Sarvam HTTP clients, tested against httpx's mock transport (no network, no key)."""
import base64
import json

import httpx
import pytest

from app.ai.sarvam import Sarvam
from app.ai.sarvam.cache import ResponseCache
from app.ai.sarvam.chat import ChatClient
from app.ai.sarvam.docai import DocumentAIClient
from app.ai.sarvam.errors import SarvamError
from app.ai.sarvam.stt import SpeechToTextClient
from app.ai.sarvam.transport import SarvamTransport
from app.ai.sarvam.tts import TextToSpeechClient
from app.config import Settings


def transport(handler, retries=2):
    client = httpx.Client(base_url="https://api.test", headers={"api-subscription-key": "KEY"}, transport=httpx.MockTransport(handler))
    return SarvamTransport("KEY", "https://api.test", 5, retries, client=client, backoff_s=0)


# ---- cache
def test_cache_key_depends_on_every_part():
    k = ResponseCache.key
    assert k("a", "x", b"y") == k("a", "x", b"y") and k("a", "x") != k("a", "z") and k("a", "x") != k("b", "x")
    assert k("a", "ab", "c") != k("a", "a", "bc")  # separator prevents collisions


def test_cache_computes_once(tmp_path):
    cache, calls = ResponseCache(str(tmp_path / "c")), []
    assert cache.get_or_set("k", lambda: calls.append(1) or {"v": 1}) == {"v": 1}
    assert cache.get_or_set("k", lambda: calls.append(1) or {"v": 2}) == {"v": 1} and len(calls) == 1


def test_cache_survives_new_instance(tmp_path):
    ResponseCache(str(tmp_path)).get_or_set("k", lambda: {"v": 7})
    assert ResponseCache(str(tmp_path)).get_or_set("k", lambda: {"v": 8}) == {"v": 7}


# ---- transport
def test_transport_sends_auth_header_and_returns_json():
    seen = {}

    def handler(req):
        seen["key"] = req.headers["api-subscription-key"]
        return httpx.Response(200, json={"ok": 1})
    assert transport(handler).request("GET", "/x") == {"ok": 1} and seen["key"] == "KEY"


def test_transport_retries_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})
    assert transport(handler).request("GET", "/x") == {"ok": True} and len(calls) == 3


def test_transport_gives_up_after_retries_with_status():
    with pytest.raises(SarvamError) as e:
        transport(lambda req: httpx.Response(429, text="slow down"), retries=1).request("GET", "/x")
    assert e.value.status_code == 429 and "slow down" in str(e.value)


def test_transport_does_not_retry_client_errors():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, text="bad")
    with pytest.raises(SarvamError):
        transport(handler).request("GET", "/x")
    assert len(calls) == 1


def test_transport_retries_timeouts_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ReadTimeout("hung", request=req)
        return httpx.Response(200, json={"ok": True})
    assert transport(handler).request("GET", "/x") == {"ok": True} and len(calls) == 3


def test_transport_timeout_after_retries_is_a_clear_sarvam_error():
    def handler(req):
        raise httpx.ConnectTimeout("no route", request=req)
    with pytest.raises(SarvamError, match="ConnectTimeout"):
        transport(handler, retries=1).request("GET", "/x")


# ---- chat
def chat_client(tmp_path, handler=None, seen=None):
    def default(req):
        if seen is not None:
            seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "namaste"}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}})
    return ChatClient(transport(handler or default), ResponseCache(str(tmp_path)), "sarvam-105b")


def test_chat_request_shape_and_reasoning_off_by_default(tmp_path):
    seen = []
    msg = chat_client(tmp_path, seen=seen).complete([{"role": "user", "content": "hi"}])
    body = seen[0]
    assert msg["content"] == "namaste" and body["model"] == "sarvam-105b" and body["reasoning_effort"] is None
    assert body["temperature"] == 0.2 and body["max_tokens"] == 2048 and "tools" not in body


def test_chat_reasoning_flag_and_tools_forwarded(tmp_path):
    seen = []
    tools = [{"type": "function", "function": {"name": "t"}}]
    chat_client(tmp_path, seen=seen).complete([{"role": "user", "content": "hi"}], tools=tools, reasoning=True)
    assert seen[0]["reasoning_effort"] == "low" and seen[0]["tools"] == tools and seen[0]["tool_choice"] == "auto"


def test_chat_full_returns_usage_and_responses_are_cached(tmp_path):
    seen = []
    c = chat_client(tmp_path, seen=seen)
    a = c.complete_full([{"role": "user", "content": "hi"}])
    b = c.complete_full([{"role": "user", "content": "hi"}])
    assert a == b and a["usage"]["total_tokens"] == 7 and len(seen) == 1


def test_chat_cache_distinguishes_requests(tmp_path):
    seen = []
    c = chat_client(tmp_path, seen=seen)
    c.complete([{"role": "user", "content": "one"}])
    c.complete([{"role": "user", "content": "two"}])
    assert len(seen) == 2


# ---- speech to text
def test_stt_multipart_fields_and_result_shape(tmp_path):
    seen = {}

    def handler(req):
        seen["ctype"], seen["body"] = req.headers["content-type"], req.content
        return httpx.Response(200, json={"transcript": "इस हफ्ते कितना देना है?", "language_code": "hi-IN"})
    stt = SpeechToTextClient(transport(handler), ResponseCache(str(tmp_path)), "saaras:v4")
    out = stt.transcribe(b"RIFFdata", "a.wav", "codemix")
    assert out == {"transcript": "इस हफ्ते कितना देना है?", "language_code": "hi-IN"}
    assert seen["ctype"].startswith("multipart/form-data") and b"saaras:v4" in seen["body"] and b"codemix" in seen["body"]


def test_stt_missing_fields_default_safely(tmp_path):
    stt = SpeechToTextClient(transport(lambda r: httpx.Response(200, json={})), ResponseCache(str(tmp_path)), "m")
    assert stt.transcribe(b"x") == {"transcript": "", "language_code": None}


# ---- text to speech
def test_tts_decodes_and_joins_base64_chunks(tmp_path):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"audios": [base64.b64encode(b"AB").decode(), base64.b64encode(b"CD").decode()]})
    tts = TextToSpeechClient(transport(handler), ResponseCache(str(tmp_path)), "bulbul:v4-flash", "simran_en_customer")
    chunks = [base64.b64encode(b"AB").decode(), base64.b64encode(b"CD").decode()]
    assert tts.synthesize("namaste", "hi-IN") == base64.b64decode("".join(chunks))  # joined then decoded, as Sarvam documents
    assert seen[0] == {"text": "namaste", "language_code": "hi-IN", "model": "bulbul:v4-flash", "speaker": "simran_en_customer"}
    assert len(seen) == 1  # second call served from cache


# ---- document AI
def docai(tmp_path, statuses, results=None, timeout=5.0):
    calls, queue = [], list(statuses)

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            return httpx.Response(200, json={"job_id": "J1", "status": "pending"})
        if req.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": queue.pop(0) if len(queue) > 1 else queue[0]})
        return httpx.Response(200, json={"result": results or {"invoice_no": "ST-1"}})
    return DocumentAIClient(transport(handler), ResponseCache(str(tmp_path)), 0, timeout), calls


SCHEMA = {"type": "object", "properties": {"invoice_no": {"type": "string", "description": "n"}}}


def test_docai_submit_poll_fetch(tmp_path):
    client, calls = docai(tmp_path, ["pending", "running", "completed"])
    assert client.extract(b"img", "b.jpg", SCHEMA) == {"invoice_no": "ST-1"}
    assert calls[0] == ("POST", "/doc-ai/v1/job/extract") and [c[1] for c in calls].count("/doc-ai/v1/job/J1/status") == 3
    assert calls[-1] == ("GET", "/doc-ai/v1/job/J1/results")


def test_docai_partial_completion_is_usable(tmp_path):
    client, _ = docai(tmp_path, ["partially_completed"])
    assert client.extract(b"img", "b.jpg", SCHEMA) == {"invoice_no": "ST-1"}


@pytest.mark.parametrize("status", ["failed", "rejected"])
def test_docai_failed_job_raises(tmp_path, status):
    client, _ = docai(tmp_path, [status])
    with pytest.raises(SarvamError, match=status):
        client.extract(b"img", "b.jpg", SCHEMA)


def test_docai_times_out(tmp_path):
    client, _ = docai(tmp_path, ["running"], timeout=0.05)
    with pytest.raises(SarvamError, match="timed out"):
        client.extract(b"img", "b.jpg", SCHEMA)


def test_docai_schema_sent_as_json_string_and_result_cached(tmp_path):
    bodies = []

    def handler(req):
        if req.method == "POST":
            bodies.append(req.content)
            return httpx.Response(200, json={"job_id": "J"})
        return httpx.Response(200, json={"status": "completed"} if req.url.path.endswith("/status") else {"result": {"a": 1}})
    c = DocumentAIClient(transport(handler), ResponseCache(str(tmp_path)), 0, 5)
    assert c.extract(b"img", "b.jpg", SCHEMA) == {"a": 1} and c.extract(b"img", "b.jpg", SCHEMA) == {"a": 1}
    assert len(bodies) == 1 and b'name="schema"' in bodies[0] and b'"invoice_no"' in bodies[0] and b'output_format' in bodies[0]


# ---- composition root
def test_sarvam_wires_all_clients_with_configured_models(tmp_path):
    s = Sarvam(Settings(sarvam_api_key="k", sarvam_cache_dir=str(tmp_path), sarvam_chat_model="m1", sarvam_stt_model="m2",
                        sarvam_tts_model="m3", sarvam_tts_speaker="spk"))
    assert (s.chat._model, s.stt._model, s.tts._model, s.tts._speaker) == ("m1", "m2", "m3", "spk")
