"""The agent as a LangGraph state machine. Same contract as ai.agent.Agent, plus durable per-thread memory.

    llm --tool calls--> tools --> llm ...            (capped at max_steps)
     |                                   |
     +--- no tool calls / error / cap ---+--> finalize  (grounding guard, router safety net, template fallback)

The graph is compiled per request because its nodes close over that request's ToolContext. Only `messages`
live in persisted state; per-turn results (tool traces, reply, source) are kept in a small closure object.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage, trim_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.ai import grounding, prompt_builder, router, templates
from app.ai.agent import APOLOGY, MAX_STEPS, AgentReply, ToolTrace, _merchant_name
from app.ai.graph.chat_model import HisaabChatModel
from app.ai.graph.tools import build_tools
from app.ai.sarvam_port import ChatPort
from app.ai.tools import registry
from app.ai.tools.context import ToolContext
from app.ai.trace import TurnTrace

log = logging.getLogger(__name__)
WINDOW = 14  # messages sent to the model; older turns stay in the thread but are not replayed


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


@dataclass
class _Turn:
    """Everything produced during one respond() call (not persisted)."""
    traces: list[ToolTrace] = field(default_factory=list)
    reply: str = ""
    source: str = "llm"
    llm_failed: bool = False
    steps: int = 0
    trace: TurnTrace = field(default_factory=lambda: TurnTrace(engine="graph"))


def thread_id(ctx: ToolContext, channel: str) -> str:
    return f"chat-{ctx.merchant_id}-{channel}"


def _this_turn_results(messages: list[AnyMessage]) -> list[dict]:
    """Tool results since the latest human message."""
    out: list[dict] = []
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, ToolMessage):
            out.append(json.loads(m.content))
    return list(reversed(out))


class GraphAgent:
    def __init__(self, chat: ChatPort, checkpointer: BaseCheckpointSaver, router_first: bool = False, max_steps: int = MAX_STEPS):
        self._model = HisaabChatModel(port=chat)
        self._checkpointer, self._router_first, self._max_steps = checkpointer, router_first, max_steps

    # ---- public API (same shape as ai.agent.Agent.respond)
    def respond(self, ctx: ToolContext, text: str, channel: str = "app", language: str = "hi",
                history: list[dict] | None = None) -> AgentReply:
        turn = _Turn()
        graph = self._build(ctx, channel, language, text, turn)
        config = {"configurable": {"thread_id": thread_id(ctx, channel)}, "recursion_limit": 40,
                  "tags": ["hisaab", f"channel:{channel}", f"role:{ctx.role}"],
                  "metadata": {"merchant_id": ctx.merchant_id, "channel": channel, "language": language}}
        seeded = [] if graph.get_state(config).values.get("messages") else _seed(history)
        graph.invoke({"messages": [*seeded, HumanMessage(text)]}, config)
        turn.trace.source = turn.source
        return AgentReply(turn.reply, turn.traces, turn.source, turn.trace)

    def clear_memory(self, ctx: ToolContext, channel: str) -> None:
        self._checkpointer.delete_thread(thread_id(ctx, channel))

    # ---- graph construction
    def _build(self, ctx: ToolContext, channel: str, language: str, user_text: str, turn: _Turn):
        system = prompt_builder.build(ctx.role, channel, language, _merchant_name(ctx.session, ctx.merchant_id), ctx.today)
        tools = build_tools(ctx)
        model = self._model.bind_tools(tools)
        route = router.route(user_text, ctx.role)

        def entry(state: State) -> str:
            return "routed" if self._router_first and route else "llm"

        def llm(state: State) -> dict:
            turn.steps += 1
            window = trim_messages(state["messages"], max_tokens=WINDOW, token_counter=len, strategy="last", start_on="human")
            try:
                with turn.trace.timed("llm", "chat") as _:
                    ai = model.invoke([SystemMessage(system), *window])
            except Exception:
                log.exception("LLM call failed")
                turn.llm_failed = True
                return {}
            usage = ai.usage_metadata or {}
            turn.trace.steps[-1].input_tokens, turn.trace.steps[-1].output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
            return {"messages": [ai]}

        def after_llm(state: State) -> str:
            if turn.llm_failed:
                return "finalize"
            last = state["messages"][-1]
            return "tools" if (last.tool_calls or last.invalid_tool_calls) else "finalize"

        def run_tools(state: State) -> dict:
            last: AIMessage = state["messages"][-1]
            out: list[ToolMessage] = []
            by_name = {t.name: t for t in tools}
            for call in last.tool_calls:
                with turn.trace.timed("tool", call["name"]):
                    tool = by_name.get(call["name"])
                    result = json.loads(tool.invoke(call["args"])) if tool else registry.execute(call["name"], call["args"], ctx)
                turn.traces.append(ToolTrace(call["name"], call["args"], result))
                out.append(ToolMessage(json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call["id"]))
            for bad in last.invalid_tool_calls:  # malformed arguments: report the error to the model like any tool failure
                result = registry.execute(bad["name"] or "", bad["args"], ctx)
                turn.traces.append(ToolTrace(bad["name"] or "", {}, result))
                out.append(ToolMessage(json.dumps(result, ensure_ascii=False, default=str), tool_call_id=bad["id"] or "bad"))
            return {"messages": out}

        def after_tools(state: State) -> str:
            return "finalize" if turn.steps >= self._max_steps else "llm"

        def finalize(state: State) -> dict:
            msgs = state["messages"]
            results = _this_turn_results(msgs)
            last_ai = msgs[-1] if msgs and isinstance(msgs[-1], AIMessage) else None
            content = ((last_ai.content if last_ai and not last_ai.tool_calls else "") or "").strip() if not turn.llm_failed else ""
            if results and not router.needs_router(route, [(t.name, t.arguments) for t in turn.traces]):
                if not content or not grounding.is_grounded(content, results, user_text):
                    turn.source = "template" if not content else "guard"
                    turn.reply = templates.render(turn.traces[-1].name, turn.traces[-1].result, language, channel)
                else:
                    turn.source, turn.reply = "llm", content
                return _replace_last(last_ai, turn.reply)
            if route:  # no tool, a failed model, or it dropped a fact to record or a supplier to scope to: the router decides
                return self._via_route(ctx, route, state, system, user_text, language, channel, turn, tools)
            if content:
                turn.source, turn.reply = "llm", content
                return {}
            turn.source, turn.reply = "apology", APOLOGY.get(language, APOLOGY["hi"])
            return {"messages": [AIMessage(turn.reply)]}

        def routed(state: State) -> dict:
            return self._via_route(ctx, route, state, system, user_text, language, channel, turn, tools)

        g = StateGraph(State)
        for name, fn in (("llm", llm), ("tools", run_tools), ("finalize", finalize), ("routed", routed)):
            g.add_node(name, fn)
        g.add_conditional_edges(START, entry, {"llm": "llm", "routed": "routed"})
        g.add_conditional_edges("llm", after_llm, {"tools": "tools", "finalize": "finalize"})
        g.add_conditional_edges("tools", after_tools, {"llm": "llm", "finalize": "finalize"})
        g.add_edge("finalize", END)
        g.add_edge("routed", END)
        return g.compile(checkpointer=self._checkpointer)

    def _via_route(self, ctx, route, state, system, user_text, language, channel, turn: _Turn, tools) -> dict:
        """Run the routed tool ourselves, then let the model phrase the result (or fall back to a template)."""
        with turn.trace.timed("tool", route.tool):
            result = registry.execute(route.tool, route.args, ctx)
        turn.traces.append(ToolTrace(route.tool, route.args, result))
        call_id = "router_call"
        call = AIMessage("", tool_calls=[{"name": route.tool, "args": route.args, "id": call_id, "type": "tool_call"}])
        tool_msg = ToolMessage(json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call_id)
        phrased = ""
        try:
            window = trim_messages([*state["messages"], call, tool_msg], max_tokens=WINDOW, token_counter=len, strategy="last", start_on="human")
            with turn.trace.timed("llm", "phrase"):
                writer = self._model.bind_tools(tools, tool_choice="none")  # Sarvam needs the tools declared alongside tool results
                answer = writer.invoke([SystemMessage(system), *window])
                phrased = (answer.content or "").strip()
                usage = answer.usage_metadata or {}
                turn.trace.steps[-1].input_tokens, turn.trace.steps[-1].output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        except Exception:
            log.exception("phrasing call failed")
        if phrased and grounding.is_grounded(phrased, [result], user_text):
            turn.source, turn.reply = "router", phrased
        else:
            turn.source, turn.reply = "template", templates.render(route.tool, result, language, channel)
        return {"messages": [call, tool_msg, AIMessage(turn.reply)]}


def _seed(history: list[dict] | None) -> list[AnyMessage]:
    return [HumanMessage(h["content"]) if h["role"] == "user" else AIMessage(h["content"]) for h in (history or [])]


def _replace_last(last_ai: AIMessage | None, text: str) -> dict:
    """Make the saved thread hold the reply the user actually saw (same id replaces the model's draft)."""
    if last_ai is not None and not last_ai.tool_calls:
        return {"messages": [AIMessage(text, id=last_ai.id)]}
    return {"messages": [AIMessage(text)]}
