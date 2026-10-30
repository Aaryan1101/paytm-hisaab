"""Voice in, voice out: audio -> speech-to-text -> agent -> text-to-speech -> stored audio URL."""
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from app.ai.agent import Agent, ToolTrace
from app.ai.audio_convert import to_wav_16k
from app.ai.sarvam_port import SttPort, TtsPort
from app.ai.speech_text import speakable
from app.ai.tools.context import ToolContext
from app.storage import MediaStore

log = logging.getLogger(__name__)
TTS_LANGUAGES = {"hi-IN", "en-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN", "gu-IN", "kn-IN", "ml-IN", "pa-IN", "od-IN"}
NOT_HEARD = {"hi": "Awaaz saaf nahi aayi. Kripya dobara bolein.", "en": "I couldn't hear that clearly. Please say it again."}


@dataclass
class VoiceReply:
    transcript: str
    language_code: str
    text: str
    audio_url: str | None
    traces: list[ToolTrace] = field(default_factory=list)
    source: str = "llm"
    trace: dict | None = None


class VoicePipeline:
    def __init__(self, stt: SttPort, tts: TtsPort, agent: Agent, media: MediaStore,
                 converter: Callable[[bytes, str], bytes] = to_wav_16k):
        self._stt, self._tts, self._agent, self._media, self._convert = stt, tts, agent, media, converter

    def handle(self, ctx: ToolContext, audio: bytes, filename: str = "audio.wav") -> VoiceReply:
        wav = self._convert(audio, filename)
        heard = self._stt.transcribe(wav, filename="audio.wav", mode="codemix")
        transcript = (heard.get("transcript") or "").strip()
        code = heard.get("language_code") or "hi-IN"
        language = "en" if code.startswith("en") else "hi"
        if not transcript:
            return VoiceReply("", code, NOT_HEARD[language], self._speak(NOT_HEARD[language], code), source="apology")
        reply = self._agent.respond(ctx, transcript, channel="voice", language=language)
        spoken = speakable(reply.text)
        return VoiceReply(transcript, code, spoken, self._speak(spoken, code), reply.traces, reply.source, reply.trace.to_dict())

    def _speak(self, text: str, language_code: str) -> str | None:
        """TTS failure must not lose the answer: the text is still returned, just without audio."""
        try:
            audio = self._tts.synthesize(text, language_code if language_code in TTS_LANGUAGES else "hi-IN")
            return self._media.save(audio, "wav", "audio").url
        except Exception:
            log.exception("text-to-speech failed")
            return None
