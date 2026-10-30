import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.ai.graph.chat_model import HisaabChatModel, from_wire, to_wire
from app.ai.graph.tools import build_tools
from app.ai.trace import TurnTrace
from tests.fakes import FakeChat, text, tool_call
from tests.helpers import make_ctx


# ---- message conversion
def test_to_wire_all_roles():
    ai = AIMessage(content="", tool_calls=[{"name": "get_dues", "args": {"period": "week"}, "id": "c1", "type": "tool_call"}])
    wire = [to_wire(m) for m in (SystemMessage("s"), HumanMessage("u"), ai, ToolMessage("{}", tool_call_id="c1"))]
    assert [w["role"] for w in wire] == ["system", "user", "assistant", "tool"]
    assert wire[2]["tool_calls"][0]["function"] == {"name": "get_dues", "arguments": '{"period": "week"}'}
    assert wire[3]["tool_call_id"] == "c1"


def test_to_wire_rejects_unknown_message_type():
    from langchain_core.messages import ChatMessage
    with pytest.raises(ValueError):
        to_wire(ChatMessage(role="x", content="y"))


def test_from_wire_parses_tool_calls_and_usage():
    msg = from_wire(tool_call("get_dues", {"period": "week"}), {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14})
    assert msg.tool_calls[0]["name"] == "get_dues" and msg.tool_calls[0]["args"] == {"period": "week"}
    assert msg.usage_metadata == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}


def test_from_wire_keeps_malformed_arguments_as_invalid_calls():
    bad = {"content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "get_dues", "arguments": "{oops"}}]}
    msg = from_wire(bad)
    assert msg.tool_calls == [] and msg.invalid_tool_calls[0]["name"] == "get_dues"


def test_from_wire_plain_text_and_non_object_args():
    assert from_wire(text("namaste")).content == "namaste"
    arr = {"content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "[1]"}}]}
    assert from_wire(arr).invalid_tool_calls


# ---- chat model
def test_model_invokes_port_and_returns_ai_message():
    chat = FakeChat([text("namaste")])
    out = HisaabChatModel(port=chat).invoke([HumanMessage("hi")])
    assert isinstance(out, AIMessage) and out.content == "namaste"
    assert chat.calls[0]["messages"] == [{"role": "user", "content": "hi"}]


def test_bind_tools_sends_openai_style_specs():
    chat = FakeChat([tool_call("get_dues", {"period": "week"})])
    ctx_tools = [{"type": "function", "function": {"name": "get_dues", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
    out = HisaabChatModel(port=chat).bind_tools(ctx_tools).invoke([HumanMessage("hi")])
    assert out.tool_calls[0]["name"] == "get_dues"
    assert chat.calls[0]["tools"][0]["function"]["name"] == "get_dues"


def test_model_uses_usage_reporting_port_when_available():
    class UsagePort:
        def complete_full(self, messages, tools=None, temperature=0.2, max_tokens=2048):
            return {"message": text("ok"), "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}
    out = HisaabChatModel(port=UsagePort()).invoke([HumanMessage("hi")])
    assert out.usage_metadata["total_tokens"] == 4


# ---- tools
def test_tools_built_per_role(seeded):
    s, ctx = seeded
    assert {t.name for t in build_tools(make_ctx(s, ctx.ramesh))} >= {"get_dues", "draft_payment", "forecast_cash"}
    assert {t.name for t in build_tools(make_ctx(s, ctx.vikas))} == {"get_receivables", "draft_reminders", "match_settlements", "suggest_credit_limit"}


def test_tool_runs_through_registry_and_returns_json(seeded):
    s, ctx = seeded
    tool = next(t for t in build_tools(make_ctx(s, ctx.ramesh)) if t.name == "get_dues")
    result = json.loads(tool.invoke({"period": "week"}))
    assert result["total"] == 112_400


def test_tool_errors_come_back_as_results_not_exceptions(seeded):
    s, ctx = seeded
    tool = next(t for t in build_tools(make_ctx(s, ctx.ramesh)) if t.name == "get_supplier_ledger")
    assert json.loads(tool.invoke({"supplier": "Zzz Qqq"}))["error"] == "not_found"


def test_tool_is_bound_to_its_own_context(seeded):
    s, ctx = seeded
    a = next(t for t in build_tools(make_ctx(s, ctx.ramesh)) if t.name == "get_dues")
    b = next(t for t in build_tools(make_ctx(s, ctx.neha)) if t.name == "get_dues")
    assert json.loads(a.invoke({"period": "week"}))["total"] != json.loads(b.invoke({"period": "week"}))["total"]


# ---- trace
def test_turn_trace_totals_and_serialisation():
    t = TurnTrace(engine="graph", source="llm")
    t.add("llm", "chat", 120.4, 10, 5)
    t.add("tool", "get_dues", 8.1)
    with t.timed("llm", "phrase"):
        pass
    d = t.to_dict()
    assert d["total_tokens"] == 15 and d["total_ms"] >= 128.5 and [s["kind"] for s in d["steps"]] == ["llm", "tool", "llm"]
    assert json.dumps(d)
