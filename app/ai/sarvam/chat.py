import json
from typing import Any

from app.ai.sarvam.cache import ResponseCache
from app.ai.sarvam.transport import SarvamTransport


class ChatClient:
    """Sarvam chat completions, including tool calling."""

    def __init__(self, transport: SarvamTransport, cache: ResponseCache, model: str):
        self._t, self._cache, self._model = transport, cache, model

    def complete(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.2,
                 max_tokens: int = 2048, reasoning: bool = False) -> dict:
        """Return the assistant message dict (content and/or tool_calls)."""
        return self.complete_full(messages, tools, temperature, max_tokens, reasoning)["message"]

    def complete_full(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.2,
                      max_tokens: int = 2048, reasoning: bool = False) -> dict:
        """Return {'message': assistant message dict, 'usage': token usage dict or None}."""
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Reasoning tokens eat max_tokens; off by default for short, deterministic replies.
            "reasoning_effort": "low" if reasoning else None,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        key = ResponseCache.key("chat", json.dumps(body, sort_keys=True, ensure_ascii=False))
        data = self._cache.get_or_set(key, lambda: self._t.request("POST", "/v1/chat/completions", json=body))
        return {"message": data["choices"][0]["message"], "usage": data.get("usage")}
