import json

import pytest
from sqlmodel import select

from app.ai.agent import Agent as NativeAgent
from app.ai.graph.agent_graph import GraphAgent
from app.ai.graph.checkpointing import memory_checkpointer
from app.models import PaymentDraft, PaymentOut
from tests.fakes import FakeChat, text, tool_call
from tests.helpers import make_ctx



@pytest.fixture(params=["native", "graph"])
def Agent(request):
    """Every behaviour below must hold for both engines: the hand-written loop and the LangGraph one."""
    def make(chat, **kw):
        return NativeAgent(chat, **kw) if request.param == "native" else GraphAgent(chat, memory_checkpointer(), **kw)
    return make


DUES_REPLY = "Is hafte 5 suppliers ko ₹1,12,400 dena hai."


def test_llm_calls_tool_then_answers(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text(DUES_REPLY)])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "whatsapp")
    assert r.source == "llm" and r.text == DUES_REPLY and r.traces[0].result["total"] == 112_400
    tool_msg = chat.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["total"] == 112_400


def test_system_prompt_has_rules_channel_language_and_context(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([text("Namaste")])
    Agent(chat).respond(make_ctx(s, ctx.ramesh), "hello", "voice", "hi")
    system = chat.calls[0]["messages"][0]["content"]
    assert "ONLY state numbers returned by tools" in system and "spoken aloud" in system
    assert "Ramesh General Store" in system and "31 October 2026" in system and "Hinglish" in system


def test_history_is_included_in_order(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([text("ok")])
    hist = [{"role": "user", "content": "pehla"}, {"role": "assistant", "content": "jawab"}]
    Agent(chat).respond(make_ctx(s, ctx.ramesh), "doosra", history=hist)
    roles = [m["content"] for m in chat.calls[0]["messages"][1:]]
    assert roles == ["pehla", "jawab", "doosra"]


def test_ungrounded_number_replaced_by_template(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text("Is hafte ₹1,25,000 dena hai.")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "whatsapp")
    assert r.source == "guard" and "₹1,12,400" in r.text and "1,25,000" not in r.text


def test_empty_llm_reply_after_tool_uses_template(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text("")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "app")
    assert r.source == "template" and "₹1,12,400" in r.text


def test_llm_that_skips_the_tool_is_overridden_by_router(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([text("Aapko ₹0 dene hain."), text(DUES_REPLY)])  # 2nd call = phrasing of the tool result
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "whatsapp")
    assert r.source == "router" and r.traces[0].name == "get_dues" and r.text == DUES_REPLY


def test_llm_failure_falls_back_to_template(seeded, Agent):
    s, ctx = seeded

    def boom(messages, tools):
        raise RuntimeError("sarvam down")
    r = Agent(FakeChat(boom)).respond(make_ctx(s, ctx.ramesh), "Paise kab kam padenge?", "app")
    assert r.source == "template" and "Thursday" in r.text and "₹38,000" in r.text


def test_llm_failure_on_unroutable_text_apologises(seeded, Agent):
    s, ctx = seeded

    def boom(messages, tools):
        raise RuntimeError("down")
    r = Agent(FakeChat(boom)).respond(make_ctx(s, ctx.ramesh), "kya haal hai", "app", "en")
    assert r.source == "apology" and "Sorry" in r.text


def test_chitchat_without_route_is_trusted(seeded, Agent):
    s, ctx = seeded
    r = Agent(FakeChat([text("Namaste! Kaise madad karun?")])).respond(make_ctx(s, ctx.ramesh), "namaste")
    assert r.source == "llm" and r.traces == []


def test_router_first_runs_tool_without_asking_llm_to_choose(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([text(DUES_REPLY)])
    r = Agent(chat, router_first=True).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "whatsapp")
    # one call, and it only writes: tools are declared (Sarvam requires that with tool results) but calling them is forbidden
    assert len(chat.calls) == 1 and chat.calls[0]["tool_choice"] == "none" and chat.calls[0]["tools"] and r.source == "router"


def test_router_first_falls_back_to_template_when_phrasing_fails(seeded, Agent):
    s, ctx = seeded

    def boom(messages, tools):
        raise RuntimeError("down")
    r = Agent(FakeChat(boom), router_first=True).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "voice")
    assert r.source == "template" and "1 lakh 12 hazaar" in r.text


def test_router_first_with_unroutable_text_uses_llm(seeded, Agent):
    s, ctx = seeded
    r = Agent(FakeChat([text("Namaste")]), router_first=True).respond(make_ctx(s, ctx.ramesh), "namaste")
    assert r.text == "Namaste"


def test_runaway_tool_loop_is_capped(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: tool_call("get_dues", {"period": "week"}))
    r = Agent(chat, max_steps=3).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "app")
    assert len(chat.calls) == 3 and r.source == "template" and len(r.traces) == 3


def test_tool_error_is_passed_to_llm_not_raised(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_supplier_ledger", {"supplier": "Zzz Qqq"}), text("Yeh supplier mujhe nahi mila.")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Zzz ka hisaab", "app")
    assert r.traces[0].result["error"] == "not_found" and r.text == "Yeh supplier mujhe nahi mila."


def test_malformed_tool_arguments_do_not_crash(seeded, Agent):
    s, ctx = seeded
    bad = {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function",
                                                                  "function": {"name": "get_dues", "arguments": "{oops"}}]}
    r = Agent(FakeChat([bad, text("Dobara bataiye.")])).respond(make_ctx(s, ctx.ramesh), "kuch aur", "app")
    assert r.traces[0].result["error"] == "bad_arguments" and r.text == "Dobara bataiye."


def test_agent_can_draft_but_never_pay(seeded, Agent):
    s, ctx = seeded
    n = len(s.exec(select(PaymentOut)).all())
    chat = FakeChat([tool_call("draft_payment", {"supplier": "Sharma", "amount": 42300}),
                     text("₹42,300 ka payment taiyaar hai. Confirm karein.")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Sharma ko pay karo", "whatsapp")
    assert r.traces[0].result["status"] == "needs_confirmation"
    assert len(s.exec(select(PaymentOut)).all()) == n and s.exec(select(PaymentDraft)).first().status == "drafted"


def test_agent_has_no_confirm_tool():
    from app.ai.tools import registry
    names = {t["function"]["name"] for r in ("retailer", "distributor") for t in registry.tool_specs(r)}
    assert not any("confirm" in n for n in names)


def test_distributor_gets_distributor_prompt_and_tools(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([text("ok")])
    Agent(chat).respond(make_ctx(s, ctx.vikas), "hello", "app")
    assert "distributor" in chat.calls[0]["messages"][0]["content"]
    assert {t["function"]["name"] for t in chat.calls[0]["tools"]} >= {"get_receivables", "draft_reminders"}


def test_distributor_router_path(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([text("Overdue retailers dikha raha hoon.")])
    r = Agent(chat, router_first=True).respond(make_ctx(s, ctx.vikas), "kaun kitna dena hai", "app")
    assert r.traces[0].name == "get_receivables"


# ---- Sarvam's own rule, found against the real API: tool results are rejected unless the tools are declared
class StrictChat(FakeChat):
    def complete(self, messages, tools=None, **kw):
        if any(m.get("role") == "tool" for m in messages) and not tools:
            raise RuntimeError("400: Tool messages found but no tools provided")
        return super().complete(messages, tools, **kw)


def test_router_phrasing_declares_tools_so_sarvam_accepts_it(seeded, Agent):
    s, ctx = seeded
    r = Agent(StrictChat([text(DUES_REPLY)]), router_first=True).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "whatsapp")
    assert r.source == "router" and r.text == DUES_REPLY   # the model phrased it; the template fallback was not needed


def test_phrasing_step_cannot_call_tools(seeded, Agent):
    s, ctx = seeded
    chat = StrictChat([text(DUES_REPLY)])
    Agent(chat, router_first=True).respond(make_ctx(s, ctx.ramesh), "Is hafte kitna dena hai?", "whatsapp")
    assert chat.calls[0]["tool_choice"] == "none"


# ---- facts the user tells us must be recorded, even if the model answers a different question (found with the live eval)
def test_model_that_ignores_a_cash_entry_is_overridden(seeded, Agent):
    s, ctx = seeded
    n = len(s.exec(select(PaymentOut).where(PaymentOut.confirmed == False)).all())  # noqa: E712
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text("Is hafte ₹1,12,400 dena hai."), text("Agarwal Dairy ko ₹3,000 cash likh liya. Confirm karein?")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Agarwal dairy ko teen hazaar cash diye", "whatsapp")
    assert r.traces[-1].name == "log_cash_payment" and r.traces[-1].result["status"] == "needs_confirmation"
    assert r.traces[-1].result["amount"] == 3000
    assert len(s.exec(select(PaymentOut).where(PaymentOut.confirmed == False)).all()) == n + 1  # noqa: E712


def test_model_that_ignores_a_stated_balance_is_overridden(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text("Is hafte ₹1,12,400 dena hai."), text("Theek hai, balance ₹40,000 note kar liya.")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "mere paas 40000 cash hai", "whatsapp")
    assert r.traces[-1].name == "set_cash_balance"
    s.refresh(ctx.ramesh)
    assert ctx.ramesh.opening_balance == 40_000


def test_a_correct_cash_entry_is_not_run_twice(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("log_cash_payment", {"supplier": "Agarwal dairy", "amount": 3000}), text("Agarwal Dairy ko ₹3,000 cash likh liya. Confirm karein?")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Agarwal dairy ko teen hazaar cash diye", "whatsapp")
    assert [t.name for t in r.traces] == ["log_cash_payment"]
    assert len(s.exec(select(PaymentOut).where(PaymentOut.confirmed == False)).all()) == 1  # noqa: E712


def test_read_only_questions_are_not_overridden_by_the_router(seeded, Agent):
    """Only record-this phrases force a tool. If the model picks a different read tool the answer stands."""
    s, ctx = seeded
    chat = FakeChat([tool_call("get_supplier_ledger", {"supplier": "Sharma"}), text("Sharma Traders ka ₹73,800 baaki hai.")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Sharma ko kitna dena hai?", "whatsapp")
    assert [t.name for t in r.traces] == ["get_supplier_ledger"] and r.source == "llm"


def test_model_that_drops_the_supplier_scope_is_overridden(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week"}), text("Is hafte 5 suppliers ko ₹1,12,400 dena hai."),
                     text("Sharma Traders ko ₹42,300 dena hai.")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Sharma ko kitna dena hai?", "whatsapp")
    assert r.traces[-1].name == "get_dues" and r.traces[-1].arguments.get("supplier") == "sharma"
    assert r.traces[-1].result["total"] == 42_300 and "42,300" in r.text


def test_a_correctly_scoped_call_is_left_alone(seeded, Agent):
    s, ctx = seeded
    chat = FakeChat([tool_call("get_dues", {"period": "week", "supplier": "Sharma"}), text("Sharma Traders ko ₹42,300 dena hai.")])
    r = Agent(chat).respond(make_ctx(s, ctx.ramesh), "Sharma ko kitna dena hai?", "whatsapp")
    assert len(r.traces) == 1 and r.source == "llm"
