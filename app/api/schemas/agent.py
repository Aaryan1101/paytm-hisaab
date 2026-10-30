from typing import Any

from pydantic import BaseModel


class ChatIn(BaseModel):
    merchant_id: int
    text: str
    channel: str = "app"
    language: str | None = None
    history: list[dict[str, str]] | None = None


class ToolCallOut(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class ChatOut(BaseModel):
    text: str
    tool_calls: list[ToolCallOut]
    source: str
    trace: dict[str, Any] = {}  # engine, answering path, per-step latency and tokens


class VoiceOut(BaseModel):
    transcript: str
    language_code: str
    text: str
    audio_url: str | None
    tool_calls: list[ToolCallOut]
    source: str


class EventOut(BaseModel):
    id: int
    text: str
