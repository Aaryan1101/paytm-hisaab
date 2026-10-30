"""One agent for every channel: LLM with tool calling, a router safety net, and a grounding guard on numbers."""
import json
import logging
from dataclasses import dataclass, field

from sqlmodel import Session

from app.ai import grounding, prompt_builder, router, templates
from app.ai.sarvam_port import ChatPort
from app.ai.tools import registry
from app.ai.tools.context import ToolContext
from app.ai.trace import TurnTrace
from app.models import Merchant

log = logging.getLogger(__name__)
MAX_STEPS = 4
APOLOGY = {"hi": "Maaf kijiye, abhi jawab nahi de pa raha. Thodi der baad dobara poochhiye.",
           "en": "Sorry, I can't answer right now. Please try again shortly."}


@dataclass
class ToolTrace:
    name: str
    arguments: dict
    result: dict


@dataclass
class AgentReply:
    text: str
    traces: list[ToolTrace] = field(default_factory=list)
    source: str = "llm"  # llm | router | template | guard | apology
    trace: TurnTrace = field(default_factory=TurnTrace)


class Agent:
    def __init__(self, chat: ChatPort, router_first: bool = False, max_steps: int = MAX_STEPS):
        self._chat, self._router_first, self._max_steps = chat, router_first, max_steps

    def respond(self, ctx: ToolContext, text: str, channel: str = "app", language: str = "hi",
                history: list[dict] | None = None) -> AgentReply:
        name = _merchant_name(ctx.session, ctx.merchant_id)
        system = prompt_builder.build(ctx.role, channel, language, name, ctx.today)
        messages = [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": text}]
        route = router.route(text, ctx.role)
        trace = TurnTrace(engine="native")
        reply = self._respond(ctx, route, messages, channel, language, text, trace)
        trace.source = reply.source
        reply.trace = trace
        return reply

    def _respond(self, ctx, route, messages, channel, language, text, trace) -> AgentReply:
        if self._router_first and route:
            return self._answer_via_route(ctx, route, messages, channel, language, text, trace)
        try:
            reply = self._llm_loop(ctx, messages, channel, language, text, trace)
        except Exception:
            log.exception("LLM loop failed")
            reply = None
        if reply is not None and (reply.traces or route is None):
            return reply
        # LLM failed, or answered a data question without calling any tool: don't trust it for numbers
        return (self._answer_via_route(ctx, route, messages, channel, language, text, trace) if route
                else AgentReply(APOLOGY.get(language, APOLOGY["hi"]), source="apology"))

    # -- LLM path
    def _llm_loop(self, ctx, messages, channel, language, user_text, trace) -> AgentReply:
        traces: list[ToolTrace] = []
        specs = registry.tool_specs(ctx.role)
        for _ in range(self._max_steps):
            with trace.timed("llm", "chat"):
                msg = self._chat.complete(messages, tools=specs)
            calls = msg.get("tool_calls") or []
            if not calls:
                return self._finish(msg.get("content") or "", traces, channel, language, user_text)
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call["function"]
                with trace.timed("tool", fn["name"]):
                    result = registry.execute(fn["name"], fn.get("arguments"), ctx)
                traces.append(ToolTrace(fn["name"], _safe_args(fn.get("arguments")), result))
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False, default=str)})
        return self._finish("", traces, channel, language, user_text)

    def _finish(self, content, traces, channel, language, user_text) -> AgentReply:
        content = content.strip()
        if traces and (not content or not grounding.is_grounded(content, [t.result for t in traces], user_text)):
            source = "template" if not content else "guard"
            return AgentReply(templates.render(traces[-1].name, traces[-1].result, language, channel), traces, source)
        return AgentReply(content or APOLOGY.get(language, APOLOGY["hi"]), traces, "llm" if content else "apology")

    # -- router path
    def _answer_via_route(self, ctx, route: router.Route, messages, channel, language, user_text, trace) -> AgentReply:
        with trace.timed("tool", route.tool):
            result = registry.execute(route.tool, route.args, ctx)
        tool_trace = ToolTrace(route.tool, route.args, result)
        fallback = templates.render(route.tool, result, language, channel)
        call_id = "router_call"
        phrased = [*messages, {"role": "assistant", "content": "", "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": route.tool, "arguments": json.dumps(route.args)}}]},
            {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False, default=str)}]
        try:
            with trace.timed("llm", "phrase"):
                text = (self._chat.complete(phrased).get("content") or "").strip()
        except Exception:
            text = ""
        if text and grounding.is_grounded(text, [result], user_text):
            return AgentReply(text, [tool_trace], "router")
        return AgentReply(fallback, [tool_trace], "template")


def _merchant_name(session: Session, merchant_id: int) -> str:
    m = session.get(Merchant, merchant_id)
    return m.name if m else "the merchant"


def _safe_args(raw) -> dict:
    try:
        v = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}
