"""Run the demo-phrase eval against the real agent and Sarvam, and print a report.

Usage: uv run python -m scripts.eval_agent [--cases evals/demo_phrases.json] [--engine graph|native] [--langsmith]
Exit code is 1 if any case fails, so it can gate a deploy or a demo.
"""
import argparse
import sys

from sqlmodel import Session

from app.bootstrap import ensure_seeded
from app.config import settings
from app.container import build_container
from app.db import engine
from app.evals.runner import format_report, load_cases, run_cases, upload_to_langsmith


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="evals/demo_phrases.json")
    ap.add_argument("--engine", choices=["graph", "native"], default=settings.agent_engine)
    ap.add_argument("--langsmith", action="store_true", help="also create a LangSmith dataset from the cases")
    args = ap.parse_args()
    settings.agent_engine = args.engine
    ensure_seeded(engine)
    container = build_container(settings)
    cases = load_cases(args.cases)
    with Session(engine) as session:
        results = run_cases(session, container, cases)
    print(format_report(results))
    if args.langsmith:
        from langsmith import Client
        print("LangSmith dataset:", upload_to_langsmith(Client(), cases, "hisaab-demo-phrases"))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
