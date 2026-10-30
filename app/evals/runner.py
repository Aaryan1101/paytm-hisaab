"""Runs the agent over a dataset of phrases and scores tool choice, arguments, reply content and safety."""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from app import clock
from app.ai.tools.context import ToolContext
from app.models import Merchant

MERCHANT_NAMES = {"ramesh": "Ramesh General Store", "neha": "Gupta Wholesale", "vikas": "Sharma Traders"}


@dataclass
class Case:
    id: str
    merchant: str
    text: str
    channel: str = "whatsapp"
    language: str = "hi"
    expect_tool: str | None = None  # None means "should answer without any tool"
    expect_args: dict = field(default_factory=dict)  # strings match case-insensitively as substrings
    expect_reply_any: list[list[str]] = field(default_factory=list)  # each group: at least one alternative must appear
    forbid_in_reply: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case: Case
    failures: list[str]
    tool: str | None  # comma-separated names of every tool the agent called
    reply: str
    source: str
    ms: float
    tokens: int

    @property
    def passed(self) -> bool:
        return not self.failures


def load_cases(path: str | Path) -> list[Case]:
    return [Case(**c) for c in json.loads(Path(path).read_text())]


def _arg_matches(expected, actual) -> bool:
    if isinstance(expected, str):
        return isinstance(actual, str) and expected.casefold() in actual.casefold()
    return expected == actual


def score(case: Case, calls: list[tuple[str, dict]], reply: str) -> list[str]:
    """`calls` = every (tool, arguments) the agent made. The expected tool may appear anywhere (an extra lookup is fine);
    a case that expects no tool fails if any was used."""
    failures = []
    names = [n for n, _ in calls]
    if case.expect_tool is None:
        if names:
            failures.append(f"expected no tool, got {names}")
    elif case.expect_tool not in names:
        failures.append(f"expected tool {case.expect_tool!r}, got {names or None}")
    args = next((a for n, a in calls if n == case.expect_tool), {})
    for k, v in case.expect_args.items():
        if case.expect_tool in names and not _arg_matches(v, args.get(k)):
            failures.append(f"arg {k}: expected {v!r}, got {args.get(k)!r}")
    for group in case.expect_reply_any:
        if not any(alt in reply for alt in group):
            failures.append(f"reply lacks any of {group}")
    for bad in case.forbid_in_reply:
        if bad in reply:
            failures.append(f"reply must not contain {bad!r}")
    return failures


def run_cases(session: Session, container, cases: list[Case]) -> list[CaseResult]:
    merchants = {key: session.exec(select(Merchant).where(Merchant.name == name)).one() for key, name in MERCHANT_NAMES.items()}
    results = []
    for case in cases:
        m = merchants[case.merchant]
        ctx = ToolContext(session, m.id, m.role, clock.today(), clock.now(), container.notifier(session), container.media, container.reminders)
        if hasattr(container.agent, "clear_memory"):
            container.agent.clear_memory(ctx, case.channel)  # every case starts from a clean conversation
        start = time.perf_counter()
        reply = container.agent.respond(ctx, case.text, case.channel, case.language)
        ms = (time.perf_counter() - start) * 1000
        calls = [(t.name, t.arguments) for t in reply.traces]
        results.append(CaseResult(case, score(case, calls, reply.text), ", ".join(n for n, _ in calls) or None,
                                  reply.text, reply.source, round(ms), reply.trace.total_tokens))
    session.rollback()  # evals must not leave pending cash entries or drafts behind
    return results


def format_report(results: list[CaseResult]) -> str:
    lines = [f"{'':2}{'case':<22}{'tools':<40}{'path':<10}{'ms':>7}{'tok':>6}"]
    for r in results:
        lines.append(f"{'✓' if r.passed else '✗':2}{r.case.id:<22}{(r.tool or '-')[:38]:<40}{r.source:<10}{r.ms:>7}{r.tokens:>6}")
        lines.extend(f"    - {f}" for f in r.failures)
    passed = sum(r.passed for r in results)
    avg = sum(r.ms for r in results) / len(results) if results else 0
    lines.append(f"\n{passed}/{len(results)} passed · avg {avg:.0f} ms · {sum(r.tokens for r in results)} tokens")
    return "\n".join(lines)


def upload_to_langsmith(client, cases: list[Case], dataset_name: str) -> str:
    """Create (or reuse) a LangSmith dataset holding the cases, so runs can be compared over time there."""
    existing = list(client.list_datasets(dataset_name=dataset_name))
    dataset = existing[0] if existing else client.create_dataset(dataset_name, description="Hisaab agent demo phrases")
    if not existing:
        client.create_examples(
            dataset_id=dataset.id,
            inputs=[{"text": c.text, "merchant": c.merchant, "channel": c.channel} for c in cases],
            outputs=[{"expect_tool": c.expect_tool, "expect_args": c.expect_args, "expect_reply_any": c.expect_reply_any} for c in cases])
    return str(dataset.id)
