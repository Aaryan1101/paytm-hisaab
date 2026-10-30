import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.agent import Agent
from app.ai.graph.agent_graph import GraphAgent
from app.ai.graph.checkpointing import memory_checkpointer
from app.ai.graph.tracing import configure_langsmith
from app.config import Settings
from app.container import Container
from app.evals.runner import Case, format_report, load_cases, run_cases, score, upload_to_langsmith
from app.models import PaymentDraft, PaymentOut
from app.storage import MediaStore
from tests.fakes import FakeChat, FakeDocAI, FakeStt, FakeTts, text, tool_call


# ---- LangSmith switch
def test_langsmith_off_by_default_and_without_key():
    env = {}
    assert configure_langsmith(Settings(), env) is False and env == {}
    assert configure_langsmith(Settings(langsmith_tracing=True), env) is False and env == {}
    assert configure_langsmith(Settings(langsmith_api_key="k"), env) is False


def test_langsmith_on_sets_environment():
    env = {}
    assert configure_langsmith(Settings(langsmith_tracing=True, langsmith_api_key="k", langsmith_project="p"), env) is True
    assert env == {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "k", "LANGSMITH_PROJECT": "p"}


# ---- scoring
def case(**kw):
    return Case(id="c", merchant="ramesh", text="t", **kw)


def test_score_passes_when_everything_matches():
    c = case(expect_tool="get_dues", expect_args={"supplier": "sharma"}, expect_reply_any=[["1,12,400", "112400"]])
    assert score(c, [("get_dues", {"supplier": "Sharma Traders"})], "Total ₹1,12,400") == []


def test_score_reports_each_kind_of_failure():
    c = case(expect_tool="get_dues", expect_args={"amount": 3000}, expect_reply_any=[["38,000"]], forbid_in_reply=["ho gaya"])
    f = score(c, [("forecast_cash", {"amount": 5})], "payment ho gaya")
    assert len(f) == 3 and "expected tool" in f[0]  # args are only checked when the expected tool ran


def test_no_tool_expected_fails_if_a_tool_ran():
    assert score(case(expect_tool=None), [], "namaste") == []
    assert score(case(expect_tool=None), [("get_dues", {})], "x")[0].startswith("expected no tool")


def test_expected_tool_may_follow_an_extra_lookup():
    c = case(expect_tool="draft_reminders", expect_args={"language": "en"})
    assert score(c, [("get_receivables", {}), ("draft_reminders", {"language": "en"})], "ok") == []
    assert score(c, [("get_receivables", {}), ("draft_reminders", {"language": "hi"})], "ok")


def test_string_args_match_case_insensitively_numbers_exactly():
    c = case(expect_tool="x", expect_args={"s": "agarwal", "n": 3000})
    assert score(c, [("x", {"s": "AGARWAL DAIRY", "n": 3000})], "") == [] and score(c, [("x", {"s": "agarwal", "n": 3001})], "")


# ---- dataset + runner
DATASET = Path(__file__).resolve().parents[1] / "evals" / "demo_phrases.json"


def test_shipped_dataset_is_valid_and_covers_the_demo_phrases():
    cases = load_cases(DATASET)
    ids = {c.id for c in cases}
    assert len(cases) >= 16 and len(ids) == len(cases)
    assert {"dues-hinglish", "forecast", "cash-log", "pay-is-draft-only", "chitchat-no-tool"} <= ids
    assert {c.merchant for c in cases} == {"ramesh", "neha", "vikas"}


def container(chat, engine):
    c = Container(chat, FakeDocAI({}), FakeStt(), FakeTts(), MediaStore("/tmp/eval-media", "http://x"), agent_engine=engine)
    return c


@pytest.mark.parametrize("engine", ["native", "graph"])
def test_runner_scores_a_scripted_agent_and_leaves_no_side_effects(seeded, engine):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: text("Namaste!") if m[-1]["content"] == "namaste" else tool_call("get_dues", {"period": "week"}))
    cases = [Case(id="dues", merchant="ramesh", text="Is hafte kitna dena hai?", expect_tool="get_dues", expect_reply_any=[["1,12,400"]]),
             Case(id="wrong-tool", merchant="ramesh", text="Is hafte kitna dena hai?", expect_tool="forecast_cash"),
             Case(id="chat", merchant="ramesh", text="namaste", expect_tool=None)]
    results = run_cases(s, container(chat, engine), cases)
    assert [r.passed for r in results] == [True, False, True]
    assert results[0].source in ("template", "guard") and results[0].ms >= 0


def test_runner_rolls_back_pending_entries_created_by_cases(seeded):
    s, ctx = seeded
    n_pay, n_draft = len(s.exec(__import__("sqlmodel").select(PaymentOut)).all()), len(s.exec(__import__("sqlmodel").select(PaymentDraft)).all())
    chat = FakeChat(lambda m, t: tool_call("log_cash_payment", {"supplier": "Agarwal", "amount": 3000}) if not any(x["role"] == "tool" for x in m) else text("Confirm karein?"))
    run_cases(s, container(chat, "native"), [Case(id="cash", merchant="ramesh", text="Agarwal dairy ko teen hazaar cash diye", expect_tool="log_cash_payment")])
    assert len(s.exec(__import__("sqlmodel").select(PaymentOut)).all()) == n_pay


def test_graph_runner_starts_every_case_with_a_clean_thread(seeded):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: text("ok"))
    cases = [Case(id="a", merchant="ramesh", text="pehla", expect_tool=None), Case(id="b", merchant="ramesh", text="doosra", expect_tool=None)]
    run_cases(s, container(chat, "graph"), cases)
    assert [m["content"] for m in chat.calls[1]["messages"] if m["role"] == "user"] == ["doosra"]


def test_report_lists_failures_and_totals(seeded):
    s, ctx = seeded
    chat = FakeChat(lambda m, t: text("hi"))
    results = run_cases(s, container(chat, "native"), [Case(id="needs-tool", merchant="ramesh", text="x", expect_tool="get_dues")])
    report = format_report(results)
    assert "✗" in report and "expected tool 'get_dues', got None" in report and "0/1 passed" in report
    assert format_report([]).endswith("0/0 passed · avg 0 ms · 0 tokens")


# ---- LangSmith dataset upload (with a fake client)
class FakeLangSmith:
    def __init__(self, existing=False):
        self.existing, self.created, self.examples = existing, [], []

    def list_datasets(self, dataset_name):
        return [SimpleNamespace(id="ds-1")] if self.existing else []

    def create_dataset(self, name, description=""):
        self.created.append(name)
        return SimpleNamespace(id="ds-new")

    def create_examples(self, dataset_id, inputs, outputs):
        self.examples.append((dataset_id, inputs, outputs))


def test_upload_creates_dataset_once():
    cases = load_cases(DATASET)
    c = FakeLangSmith()
    assert upload_to_langsmith(c, cases, "d") == "ds-new"
    assert c.created == ["d"] and len(c.examples[0][1]) == len(cases) and c.examples[0][2][0]["expect_tool"] == "get_dues"
    again = FakeLangSmith(existing=True)
    assert upload_to_langsmith(again, cases, "d") == "ds-1" and again.created == [] and again.examples == []
