# Hisaab Agent: backend + AI

FastAPI service for the Hisaab Agent hackathon build. Sarvam does the AI (Document AI for bills, Saaras for speech,
Bulbul for voice, Sarvam-105B for the agent). Deterministic Python does all money maths.

## Guides
- [Backend setup](docs/01-backend-setup.md) · [Web + full API reference](docs/02-web-integration.md) · [Android](docs/03-android-integration.md) · [WhatsApp](docs/04-whatsapp-integration.md)

## Run
```
cp .env.example .env        # add SARVAM_API_KEY
make dev                    # Postgres (docker, port 5544) + API on :8000, seeds demo data on first start
make reset                  # restore the demo dataset any time
make test                   # unit + API tests (SQLite in memory, no Sarvam calls)
make openapi                # writes shared/openapi.json for the Android and web clients
```
Demo date is pinned to 2026-10-31 (`DEMO_TODAY`). Voice notes in non-WAV formats need `ffmpeg`.

## Agent engines
`AGENT_ENGINE=graph` (default) runs the agent as a LangGraph state machine with durable per-thread memory in Postgres;
`AGENT_ENGINE=native` is the original hand-written loop. Both pass the same behaviour tests (`tests/test_agent.py`).
Confirm-before-act (bills, duplicates, cash entries, payments) is one LangGraph interrupt/resume flow in
`app/ai/graph/confirmations.py`. If Postgres is unreachable at startup the graph engine falls back to in-memory state.

## Evals and tracing
```
uv run python -m scripts.eval_agent                 # 18 demo phrases against real Sarvam: tool, args, figures, safety
uv run python -m scripts.eval_agent --langsmith     # also uploads the cases as a LangSmith dataset
SARVAM_CACHE_DIR=/tmp/cold uv run python -m scripts.eval_agent   # honest latency (the default cache hides it)
```
Every reply stores a trace (engine, answering path, per-step ms and tokens) in `messages.trace_json` and returns it from
`/agent/chat`. Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` to also send turns to LangSmith.

## Layout
- `app/engine/`: pure rules (validate, reconcile, forecast, score, credit, IMS, credit limit). No I/O.
- `app/services/`: DB-backed use cases built on the engines.
- `app/ai/`: Sarvam clients, bill extraction, agent, tools, router, voice.
- `app/channels/`: outbound notifiers and the WhatsApp adapter.
- `app/api/`: thin routers and typed schemas. `app/seed/`: demo data and planted scenarios.
