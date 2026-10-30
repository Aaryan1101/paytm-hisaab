import base64

from app.ai.sarvam.cache import ResponseCache
from app.ai.sarvam.transport import SarvamTransport


class TextToSpeechClient:
    """Bulbul text-to-speech."""

    def __init__(self, transport: SarvamTransport, cache: ResponseCache, model: str, speaker: str):
        self._t, self._cache, self._model, self._speaker = transport, cache, model, speaker

    def synthesize(self, text: str, language_code: str = "hi-IN") -> bytes:
        """Return decoded WAV bytes."""
        body = {"text": text, "language_code": language_code, "model": self._model, "speaker": self._speaker}
        key = ResponseCache.key("tts", text, language_code, self._model, self._speaker)
        data = self._cache.get_or_set(key, lambda: self._t.request("POST", "/text-to-speech", json=body))
        return base64.b64decode("".join(data["audios"]))
