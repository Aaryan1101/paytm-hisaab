"""Narrow interfaces the AI code depends on, so tests can substitute fakes for Sarvam."""
from typing import Protocol


class ChatPort(Protocol):
    def complete(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.2,
                 max_tokens: int = 2048, reasoning: bool = False) -> dict: ...


class DocAIPort(Protocol):
    def extract(self, file: bytes, filename: str, schema: dict, language: str = "en-IN",
                content_type: str = "image/jpeg") -> dict: ...


class SttPort(Protocol):
    def transcribe(self, audio: bytes, filename: str = "audio.wav", mode: str = "codemix") -> dict: ...


class TtsPort(Protocol):
    def synthesize(self, text: str, language_code: str = "hi-IN") -> bytes: ...
