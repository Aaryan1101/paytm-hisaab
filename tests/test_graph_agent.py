import uuid

import pytest

from app.ai.graph.agent_graph import WINDOW, GraphAgent, thread_id
from app.ai.graph.checkpointing import memory_checkpointer, postgres_checkpointer
from app.config import settings
from tests.fakes import FakeChat, text, tool_call
from tests.helpers import make_ctx


def contents(call, roles=("user", "assistant")):
    return [m["content"] for m in call["messages"] if m["role"] in roles]


# ---- memory
def test_second_turn_sees_the_first(seeded):
    s, ctx = seeded
    chat = FakeChat([text("Namaste! Sharma ka kuch baaki hai, pay karein?"), text("Theek hai.")])
    agent = GraphAgent(chat, memory_checkpointer())
    agent.respond(make_ctx(s, ctx.ramesh), "namaste", "whatsapp")
    agent.respond(make_ctx(s, ctx.ramesh), "haan", "whatsapp")
    assert contents(chat.calls[1]) == ["namaste", "Namaste! Sharma ka kuch baaki hai, pay karein?", "haan"]


def test_memory_is_per_merchant_and_per_channel(seeded):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: text("ok"))
    agent = GraphAgent(chat, memory_checkpointer())
    agent.respond(make_ctx(s, ctx.ramesh), "ramesh secret", "whatsapp")
    agent.respond(make_ctx(s, ctx.neha), "neha here", "whatsapp")
    agent.respond(make_ctx(s, ctx.ramesh), "ramesh on app", "app")
    assert contents(chat.calls[1]) == ["neha here"] and contents(chat.calls[2]) == ["ramesh on app"]
    assert thread_id(make_ctx(s, ctx.ramesh), "whatsapp") != thread_id(make_ctx(s, ctx.ramesh), "app")


def test_client_history_only_seeds_an_empty_thread(seeded):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: text("ok"))
    agent = GraphAgent(chat, memory_checkpointer())
    hist = [{"role": "user", "content": "pehle ki baat"}, {"role": "assistant", "content": "pehla jawab"}]
    agent.respond(make_ctx(s, ctx.ramesh), "ek", "app", history=hist)
    agent.respond(make_ctx(s, ctx.ramesh), "do", "app", history=[{"role": "user", "content": "STALE"}])
    assert contents(chat.calls[0]) == ["pehle ki baat", "pehla jawab", "ek"]
    assert "STALE" not in contents(chat.calls[1]) and contents(chat.calls[1])[-1] == "do"


def test_saved_thread_holds_the_reply_the_user_saw_not_the_ungrounded_draft(seeded):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text("Is hafte ₹9,99,999 dena hai."), text("ok")])
    agent = GraphAgent(chat, memory_checkpointer())
    first = agent.respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "app")
    assert first.source == "guard"
    agent.respond(make_ctx(s, ctx.ramesh), "shukriya", "app")
    replayed = " ".join(contents(chat.calls[2]))
    assert "9,99,999" not in replayed and "₹1,12,400" in replayed


def test_clear_memory_forgets_the_thread(seeded):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: text("ok"))
    agent = GraphAgent(chat, memory_checkpointer())
    agent.respond(make_ctx(s, ctx.ramesh), "pehla", "app")
    agent.clear_memory(make_ctx(s, ctx.ramesh), "app")
    agent.respond(make_ctx(s, ctx.ramesh), "doosra", "app")
    assert contents(chat.calls[1]) == ["doosra"]


def test_model_window_is_bounded_and_starts_on_a_user_turn(seeded):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: text("ok"))
    agent = GraphAgent(chat, memory_checkpointer())
    for i in range(20):
        agent.respond(make_ctx(s, ctx.ramesh), f"msg {i}", "app")
    sent = [m for m in chat.calls[-1]["messages"] if m["role"] != "system"]
    assert len(sent) <= WINDOW and sent[0]["role"] == "user" and sent[-1]["content"] == "msg 19"


# ---- tracing
class UsagePort:
    """Port that reports token usage like the real client does."""

    def __init__(self, script):
        self.script = list(script)

    def complete_full(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        return {"message": self.script.pop(0), "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


def test_trace_records_tokens_timing_and_path(seeded):
    s, ctx = seeded
    port = UsagePort([tool_call("get_dues", {"period": "week"}), text("Is hafte 5 suppliers ko ₹1,12,400 dena hai.")])
    r = GraphAgent(port, memory_checkpointer()).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "app")
    t = r.trace.to_dict()
    assert t["engine"] == "graph" and t["source"] == "llm" and t["total_tokens"] == 240
    assert [(x["kind"], x["name"]) for x in t["steps"]] == [("llm", "chat"), ("tool", "get_dues"), ("llm", "chat")]
    assert all(x["ms"] >= 0 for x in t["steps"])


def test_native_agent_also_traces(seeded):
    from app.ai.agent import Agent
    s, ctx = seeded
    r = Agent(FakeChat([tool_call("get_dues", {"period": "week"}), text("Is hafte ₹1,12,400 dena hai.")])).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?")
    assert r.trace.engine == "native" and [x.kind for x in r.trace.steps] == ["llm", "tool", "llm"] and r.trace.source == "llm"


def test_router_path_is_traced(seeded):
    s, ctx = seeded
    r = GraphAgent(FakeChat([text("Is hafte ₹1,12,400 dena hai.")]), memory_checkpointer(), router_first=True).respond(
        make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?")
    assert [(x.kind, x.name) for x in r.trace.steps] == [("tool", "get_dues"), ("llm", "phrase")] and r.trace.source == "router"


# ---- durable memory in real Postgres (skipped when the database isn't reachable)
@pytest.fixture
def pg_saver():
    try:
        saver = postgres_checkpointer(settings.database_url)
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not available: {e}")
    yield saver
    saver.conn.close()


def test_memory_survives_a_new_agent_and_new_saver(seeded, pg_saver):
    s, ctx = seeded
    channel = f"pgtest-{uuid.uuid4().hex[:8]}"
    first_chat = FakeChat([text("Namaste! Kaise madad karun?")])
    GraphAgent(first_chat, pg_saver).respond(make_ctx(s, ctx.ramesh), "namaste", channel)
    reopened = postgres_checkpointer(settings.database_url)  # as after a server restart
    second_chat = FakeChat([text("ok")])
    GraphAgent(second_chat, reopened).respond(make_ctx(s, ctx.ramesh), "phir se", channel)
    assert contents(second_chat.calls[0]) == ["namaste", "Namaste! Kaise madad karun?", "phir se"]
    reopened.delete_thread(thread_id(make_ctx(s, ctx.ramesh), channel))
    reopened.conn.close()
