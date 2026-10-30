import pytest

from app.ai import audio_convert
from app.ai.agent import Agent
from app.ai.audio_convert import AudioConversionError, is_wav, to_wav_16k
from app.ai.reminders import ReminderDrafter, template
from app.ai.voice import VoicePipeline
from app.storage import MediaStore
from tests.fakes import FakeChat, FakeStt, FakeTts, text, tool_call
from tests.helpers import make_ctx

WAV = b"RIFF\x00\x00\x00\x00WAVEfmt "


# ---- audio conversion
def test_wav_detection_and_passthrough():
    assert is_wav(WAV) and to_wav_16k(WAV, "a.wav") == WAV
    assert not is_wav(b"OggS....")


def test_non_wav_without_ffmpeg_raises_clear_error(monkeypatch):
    monkeypatch.setattr(audio_convert.shutil, "which", lambda _: None)
    with pytest.raises(AudioConversionError, match="ffmpeg is not installed"):
        to_wav_16k(b"OggSxxxx", "note.ogg")


def test_non_wav_converted_via_ffmpeg(monkeypatch):
    monkeypatch.setattr(audio_convert.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    seen = {}

    def fake_run(cmd, input, capture_output, timeout):
        seen["cmd"], seen["input"] = cmd, input

        class P:
            returncode, stdout, stderr = 0, WAV, b""
        return P()
    monkeypatch.setattr(audio_convert.subprocess, "run", fake_run)
    assert to_wav_16k(b"OggSxxxx", "n.ogg") == WAV
    assert "16000" in seen["cmd"] and seen["input"] == b"OggSxxxx"


def test_ffmpeg_failure_raises(monkeypatch):
    monkeypatch.setattr(audio_convert.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    class P:
        returncode, stdout, stderr = 1, b"", b"bad data"
    monkeypatch.setattr(audio_convert.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(AudioConversionError, match="bad data"):
        to_wav_16k(b"junk", "x.ogg")


# ---- pipeline
def pipeline(chat, stt=None, tts=None, tmp=None, converter=lambda a, f: a):
    return VoicePipeline(stt or FakeStt(), tts or FakeTts(), Agent(chat), MediaStore(str(tmp), "http://h"), converter)


def test_voice_round_trip(seeded, tmp_path):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text("Is hafte 1 lakh 12 hazaar dena hai, sabse pehle Gupta. Baaki baad mein.")])
    stt, tts = FakeStt(), FakeTts()
    r = pipeline(chat, stt, tts, tmp_path).handle(make_ctx(s, ctx.ramesh), WAV)
    assert r.transcript == "Is hafte kitna dena hai?" and r.source == "llm"
    assert tts.calls[0]["language_code"] == "hi-IN" and stt.calls[0]["mode"] == "codemix"
    assert r.audio_url.startswith("http://h/media/audio/") and (tmp_path / "audio").exists()
    assert "voice" not in r.text and r.traces[0].name == "get_dues"


def test_voice_reply_is_trimmed_to_two_spoken_sentences(seeded, tmp_path):
    s, ctx = seeded
    chat = FakeChat([text("*Ek.* Do. Teen. Chaar.")])
    tts = FakeTts()
    r = pipeline(chat, FakeStt("namaste"), tts, tmp_path).handle(make_ctx(s, ctx.ramesh), WAV)
    assert r.text == "Ek. Do." and tts.calls[0]["text"] == "Ek. Do."


def test_english_speech_gets_english_agent_and_voice(seeded, tmp_path):
    s, ctx = seeded
    chat, tts = FakeChat([text("Hello there.")]), FakeTts()
    pipeline(chat, FakeStt("hello", "en-IN"), tts, tmp_path).handle(make_ctx(s, ctx.ramesh), WAV)
    assert tts.calls[0]["language_code"] == "en-IN" and "Default to English" in chat.calls[0]["messages"][0]["content"]


def test_unsupported_language_speaks_hindi(seeded, tmp_path):
    s, ctx = seeded
    tts = FakeTts()
    pipeline(FakeChat([text("ok.")]), FakeStt("x", "xx-YY"), tts, tmp_path).handle(make_ctx(s, ctx.ramesh), WAV)
    assert tts.calls[0]["language_code"] == "hi-IN"


def test_silence_asks_to_repeat_without_calling_agent(seeded, tmp_path):
    s, ctx = seeded
    chat = FakeChat([])
    r = pipeline(chat, FakeStt(""), None, tmp_path).handle(make_ctx(s, ctx.ramesh), WAV)
    assert "dobara bolein" in r.text and chat.calls == [] and r.source == "apology" and r.audio_url


def test_tts_failure_still_returns_text(seeded, tmp_path):
    s, ctx = seeded

    class BrokenTts:
        def synthesize(self, text, language_code="hi-IN"):
            raise RuntimeError("tts down")
    r = pipeline(FakeChat([text("Namaste.")]), FakeStt("namaste"), BrokenTts(), tmp_path).handle(make_ctx(s, ctx.ramesh), WAV)
    assert r.text == "Namaste." and r.audio_url is None


def test_conversion_is_applied_before_stt(seeded, tmp_path):
    s, ctx = seeded
    stt = FakeStt()
    pipeline(FakeChat([text("ok.")]), stt, tmp=tmp_path, converter=lambda a, f: WAV).handle(make_ctx(s, ctx.ramesh), b"OggS-not-wav", "n.ogg")
    assert stt.calls[0]["size"] == len(WAV)


def test_s9_cash_voice_note_logs_pending_payment(seeded, tmp_path):
    s, ctx = seeded
    chat = FakeChat([text("Agarwal Dairy ko ₹3,000 cash likh liya. Confirm karein?")])
    stt = FakeStt("Agarwal dairy ko teen hazaar cash diye")
    r = VoicePipeline(stt, FakeTts(), Agent(chat, router_first=True), MediaStore(str(tmp_path), "http://h"), lambda a, f: a).handle(make_ctx(s, ctx.ramesh), WAV)
    assert r.traces[0].name == "log_cash_payment" and r.traces[0].result["amount"] == 3000
    assert r.traces[0].result["status"] == "needs_confirmation"


# ---- reminders
def test_template_tone_and_amount():
    t = template("Shree Kirana", "Sharma Traders", 42300, 12, "firm", "hi")
    assert "₹42,300" in t and "12 din" in t and "Shree Kirana" in t


def test_reminder_uses_llm_text_when_amount_correct():
    chat = FakeChat([text("Namaste Shree Kirana, ₹42,300 12 din se baaki hain. Kripya pay karein.")])
    out = ReminderDrafter(chat)("Shree Kirana", "Sharma", 42300, 12, "firm", "hi")
    assert out.startswith("Namaste Shree") and "firm" in chat.calls[0]["messages"][0]["content"]


def test_reminder_rejects_wrong_amount():
    chat = FakeChat([text("Namaste, ₹50,000 baaki hain.")])
    out = ReminderDrafter(chat)("Shree Kirana", "Sharma", 42300, 12, "firm", "hi")
    assert "₹42,300" in out and "50,000" not in out


def test_reminder_rejects_missing_amount():
    out = ReminderDrafter(FakeChat([text("Please pay soon.")]))("A", "B", 1000, 1, "polite", "en")
    assert "₹1,000" in out


def test_reminder_falls_back_on_llm_error():
    def boom(m, t):
        raise RuntimeError("x")
    assert "₹1,000" in ReminderDrafter(FakeChat(boom))("A", "B", 1000, 1, "polite", "en")


def test_reminder_without_chat_uses_template():
    assert "final reminder" in ReminderDrafter(None)("A", "B", 1000, 40, "final", "en")
