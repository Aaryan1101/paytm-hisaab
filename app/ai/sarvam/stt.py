from app.ai.sarvam.cache import ResponseCache
from app.ai.sarvam.transport import SarvamTransport


class SpeechToTextClient:
    """Saaras speech-to-text (REST, short clips)."""

    def __init__(self, transport: SarvamTransport, cache: ResponseCache, model: str):
        self._t, self._cache, self._model = transport, cache, model

    def transcribe(self, audio: bytes, filename: str = "audio.wav", mode: str = "codemix") -> dict:
        """Return {'transcript': str, 'language_code': str | None}."""
        key = ResponseCache.key("stt", audio, self._model, mode)

        def call() -> dict:
            return self._t.request(
                "POST",
                "/speech-to-text",
                files={"file": (filename, audio, "audio/wav")},
                data={"model": self._model, "mode": mode},
            )

        data = self._cache.get_or_set(key, call)
        return {"transcript": data.get("transcript", ""), "language_code": data.get("language_code")}
