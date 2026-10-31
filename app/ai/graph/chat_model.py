"""Adapts our Sarvam chat client to LangChain's chat-model interface.

We wrap our own client (not the alpha langchain-sarvamcloud package) because it sends reasoning_effort=null
correctly, caches responses and retries. LangGraph only needs something that looks like a BaseChatModel.
"""
import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import tool_call as make_tool_call
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict


def to_wire(m: BaseMessage) -> dict:
    """LangChain message -> Sarvam/OpenAI-style message dict."""
    if isinstance(m, SystemMessage):
        return {"role": "system", "content": m.content}
    if isinstance(m, HumanMessage):
        return {"role": "user", "content": m.content}
    if isinstance(m, ToolMessage):
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if isinstance(m, AIMessage):
        out: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
        if m.tool_calls:
            out["tool_calls"] = [{"id": tc["id"], "type": "function",
                                  "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)}}
                                 for tc in m.tool_calls]
        return out
    raise ValueError(f"Unsupported message type {type(m).__name__}")


def from_wire(message: dict, usage: dict | None = None) -> AIMessage:
    """Sarvam message dict -> AIMessage, keeping malformed tool arguments visible instead of crashing."""
    calls, invalid = [], []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
            calls.append(make_tool_call(name=fn["name"], args=args, id=raw["id"]))
        except (ValueError, KeyError) as e:
            invalid.append({"name": fn.get("name"), "args": fn.get("arguments"), "id": raw.get("id"), "error": str(e), "type": "invalid_tool_call"})
    meta = None
    if usage:
        meta = {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)}
    return AIMessage(content=message.get("content") or "", tool_calls=calls, invalid_tool_calls=invalid, usage_metadata=meta)


class HisaabChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    port: Any  # our ChatPort (ChatClient, or a fake in tests)
    temperature: float = 0.2
    max_tokens: int = 2048

    @property
    def _llm_type(self) -> str:
        return "hisaab-sarvam"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        """`tool_choice="none"` declares the tools (Sarvam requires that whenever the conversation holds tool results)
        while forbidding the model from calling any: used to phrase a result already fetched."""
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], tool_choice=tool_choice, **kwargs)

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        wire = [to_wire(m) for m in messages]
        tools, choice = kwargs.get("tools"), kwargs.get("tool_choice")
        full = getattr(self.port, "complete_full", None)
        extra = {"tool_choice": choice} if choice else {}
        if full is not None:
            result = full(wire, tools=tools, temperature=self.temperature, max_tokens=self.max_tokens, **extra)
        else:  # ports without usage reporting (test fakes)
            result = {"message": self.port.complete(wire, tools=tools, temperature=self.temperature, max_tokens=self.max_tokens, **extra), "usage": None}
        return ChatResult(generations=[ChatGeneration(message=from_wire(result["message"], result.get("usage")))])
