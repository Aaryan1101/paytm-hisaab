# Backend setup guide

Everything you need to run, configure, seed, test and demo the Hisaab Agent backend. The other guides
([web](02-web-integration.md), [Android](03-android-integration.md), [WhatsApp](04-whatsapp-integration.md)) assume the
backend is running as described here.

## 1. What runs where

```
 Android app ──┐                         ┌─ Sarvam: Document AI (bills), Saaras (speech→text),
 Web dashboard ─┼─►  FastAPI backend  ───┤          Bulbul (text→speech), Sarvam-105B (agent)
 WhatsApp ─────┘     (this repo)         └─ Postgres: ledger data + agent memory (LangGraph checkpoints)
```

- One backend serves all three channels, so an answer is identical everywhere.
- **The LLM never does money maths.** Totals, matching, forecast, score and credit are deterministic Python
  (`app/engine/`). The LLM reads bills, picks tools and phrases answers; a guard rejects any reply that contains a money
  figure the tools did not return.
- Payments are **two-step**: the agent can only *draft* one. Nothing moves until a person confirms.

## 2. Prerequisites

| Need | Why | Check |
|---|---|---|
| Python 3.11+ and [uv](https://docs.astral.sh/uv/) | runs the app | `uv --version` |
| Docker + Compose | Postgres | `docker compose version` |
| A Sarvam API key | all AI features | https://dashboard.sarvam.ai |
| `ffmpeg` (optional) | converting non-WAV voice notes (WhatsApp OGG, Android AAC) | `ffmpeg -version` |

`ffmpeg` is **only** needed if clients upload voice in a format other than WAV. WAV uploads and every non-voice feature
work without it. On Debian/Ubuntu: `sudo apt install ffmpeg`.

## 3. Quick start

```bash
cd backend_ai
cp .env.example .env          # then set SARVAM_API_KEY
make dev                      # starts Postgres (docker) and the API with auto-reload
```

`make dev` runs Postgres on **port 5544** and the API on **port 8000**. On first start the app creates the tables and
seeds the demo data automatically (`AUTO_SEED=true`). Check it:

```bash
curl localhost:8000/health        # {"ok":true}
curl localhost:8000/merchants     # Ramesh, Neha, Vikas
```

Interactive API docs: <http://localhost:8000/docs>. Machine-readable contract: `make openapi` writes
`shared/openapi.json` (generate Kotlin/TypeScript clients from it).

> **Phones on your Wi-Fi.** `make dev` listens on `localhost` only. To reach it from a phone on the same network run
> `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` instead (and open the port in your firewall).

> **Port clashes.** If something else already uses 8000 (or 5432/5433), pick another API port:
> `uv run uvicorn app.main:app --port 8010`, and set `PUBLIC_BASE_URL` to match (see §4). Postgres uses 5544 on purpose so it
> does not collide with a local Postgres on 5432.

## 4. Configuration

All settings are environment variables (read from `.env`). Defaults are in `app/config.py`.

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://hisaab:hisaab@localhost:5544/hisaab` | Postgres connection (also used for agent memory) |
| `SARVAM_API_KEY` | – | **Required** for AI. Server-side only; never ship it in an APK or web bundle |
| `SARVAM_BASE_URL` | `https://api.sarvam.ai` | |
| `SARVAM_CHAT_MODEL` | `sarvam-105b` | Agent model |
| `SARVAM_STT_MODEL` | `saaras:v4` | Speech to text |
| `SARVAM_TTS_MODEL` / `SARVAM_TTS_SPEAKER` | `bulbul:v4-flash` / `simran_en_customer` | The product's voice |
| `SARVAM_TIMEOUT_S` | `20` | Per-request timeout; timeouts are retried twice |
| `SARVAM_DOCAI_TIMEOUT_S` | `90` | Max wait for a bill-reading job |
| `SARVAM_CACHE_DIR` | `.cache/sarvam` | Every Sarvam response is cached by input hash (saves credits). Use a fresh dir for honest latency numbers |
| `AGENT_ENGINE` | `graph` | `graph` = LangGraph with durable memory; `native` = the original hand-written loop |
| `AGENT_ROUTER_FIRST` | `false` | `true` runs the keyword router first and only uses the LLM to phrase the answer. A stage safety net |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Used to build `audio_url` links. **Must be reachable by the client** (see Android guide) |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated browser origins allowed to call the API (the web dashboard) |
| `DEMO_TODAY` | `2026-10-31` | "Today" is pinned so the seeded data and demo numbers stay consistent. Unset it to use the real date |
| `AUTO_SEED` | `true` | Seed demo data on startup when the database is empty |
| `MEDIA_DIR` | `.media` | Where bill images and voice replies are stored |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | off | Send every agent turn to LangSmith |
| `WHATSAPP_*` | – | See the [WhatsApp guide](04-whatsapp-integration.md) |

## 5. Demo data

Seeding is deterministic (fixed random seed), so everyone sees the same numbers.

| id | Persona | Role | Notes |
|---|---|---|---|
| 1 | **Ramesh General Store** | retailer, GST composition | 12 suppliers, language `hi` |
| 2 | **Gupta Wholesale** (Neha) | wholesaler, regular GST | 25 suppliers, IMS applies |
| 3 | **Sharma Traders** (Vikas) | distributor | 40 retailers (Ramesh + 39 generated), language `en` |

Reset to the seed at any time (takes ~0.5 s):

```bash
make reset        # = curl -X POST localhost:8000/demo/reset
```

### Planted scenarios (what to demo, and the call that triggers it)

| # | Scenario | Where it shows |
|---|---|---|
| S1 | Duplicate bill `ST-2291` (already paid 12 Oct, ₹18,640) | `POST /invoices/ingest` with a photo of that bill, or WhatsApp |
| S2 | Short payment: ₹40,000 against a ₹42,300 bill, credit note missing | `GET /merchants/1/alerts` → `missing_credit_note` |
| S3 | Wrong GST rate (18% on an item that should be 5%) | `issues[].code == "hsn_rate_mismatch"` on ingest |
| S4 | Supplier "Kanpur Plastics" has a cancelled GSTIN | `GET /merchants/2/ims?month=2026-10` |
| S5 | Ramesh is ₹38,000 short on Thursday 5 Nov → ₹50,000 credit offer | `GET /merchants/1/forecast`, `.../credit-offer` |
| S6 | One ₹31,500 payment clears two invoices, MDR shown separately | `POST /demo/simulate-payment` |
| S7 | Payee "SHARMA TRDRS LKO" fuzzy-matched to Sharma Traders | `GET /merchants/1/alerts` → `confirm_payee` |
| S8 | Handwritten *kachcha* bill, tagged non-GST | ingest a handwritten bill |
| S9 | Voice note "Agarwal dairy ko teen hazaar cash diye" | `POST /agent/voice` or WhatsApp |
| S10 | Live payment lands matched on the distributor dashboard + soundbox chime | `POST /demo/simulate-payment`, then `GET /merchants/3/events` |

Key numbers to check after a reset: Ramesh owes **₹1,12,400** to **5** suppliers this week; shortfall **₹38,000** on
**2026-11-05**; credit offer **₹50,000**; Hisaab Score ≈ **819**.

## 6. The agent

- **Tools** (`app/ai/tools/`): 12 for retailers/wholesalers (dues, ledger, alerts, explain invoice, cash entry, credit note,
  forecast, score, credit offer, draft payment, IMS, purchase register) and 4 for distributors (receivables, reminders,
  settlements, credit limit). There is deliberately **no tool that confirms a payment**.
- **Memory:** with `AGENT_ENGINE=graph`, each (merchant, channel) pair is a conversation thread stored in Postgres, so
  follow-ups like "aur Agarwal ka?" work and survive a server restart. If Postgres is unreachable at startup the app logs a
  warning and uses in-memory state.
- **`source` field** on agent replies tells you which path answered:

| `source` | Meaning |
|---|---|
| `llm` | The model answered after calling tools; every figure was verified against tool results |
| `router` | The model skipped a needed tool, so the keyword router ran it and the model phrased the result |
| `template` | The model's reply was empty or the model was down; a fixed template answered (still correct) |
| `guard` | The model's reply contained a figure the tools never returned, so a template replaced it |
| `apology` | Nothing could answer (model down and the phrase is not a known intent) |

- **Trace:** each reply includes `trace` (engine, path, per-step `ms` and tokens) and it is stored in `messages.trace_json`.

## 7. Tests, evals, tooling

```bash
make test                                   # ~600 tests, ~80 s. SQLite in memory + fake Sarvam: no key, no network
uv run python -m scripts.eval_agent         # 16 demo phrases against REAL Sarvam: tool choice, args, figures, safety
SARVAM_CACHE_DIR=/tmp/cold uv run python -m scripts.eval_agent   # same, but honest latency (no cache hits)
uv run python -m scripts.probe_sarvam chat  # smoke-test one Sarvam call (also: tts | stt <wav> | doc <image>)
make openapi                                # refresh shared/openapi.json
```

A few tests (agent memory, pending confirmations) use the real Postgres on port 5544 and skip themselves if it is down.

## 8. Changing the database schema

There are no migrations (hackathon scope). After you change a model, drop the tables and let the app recreate and reseed:

```bash
uv run python -c "from sqlmodel import SQLModel; import app.models; from app.db import engine; SQLModel.metadata.drop_all(engine)"
make dev       # recreates tables and reseeds
```

This deletes all data in the database named by `DATABASE_URL`. Agent memory tables (`checkpoints*`) are managed by LangGraph
and are separate.

## 9. Running it for a demo

- **Public URL:** WhatsApp (and phones on another network) need to reach your laptop over HTTPS. Use a tunnel:
  `cloudflared tunnel --url http://localhost:8000` or `ngrok http 8000`. Then set `PUBLIC_BASE_URL` to that URL and restart.
- **Venue Wi-Fi:** use a phone hotspot for the backend laptop.
- **Before going on stage:** `make reset`, then `uv run python -m scripts.eval_agent` to confirm all 16 phrases still pass.
- **Safety nets:** `AGENT_ROUTER_FIRST=true` makes the demo phrases deterministic; the response cache replays anything you
  already ran, so rehearse the exact script once.

## 10. Where things live

```
app/engine/     pure rules: validate, reconcile, forecast, score, credit, ims, credit_limit   (no I/O, no LLM)
app/services/   DB-backed use cases built on the engines
app/ai/         Sarvam clients, bill extraction, agent (native + graph), tools, router, voice
app/ai/graph/   LangGraph agent, confirmations (confirm-before-act), checkpointing, tracing
app/channels/   outbound notifiers + the WhatsApp adapter
app/api/        thin routers + typed schemas        app/seed/   demo data and planted scenarios
evals/          demo-phrase dataset                 scripts/    eval, probe, test-webhook
```

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `address already in use` | Another process owns the port. Use `--port` and update `PUBLIC_BASE_URL` |
| Every AI call fails / `403` from Sarvam | `SARVAM_API_KEY` missing or wrong in `.env` |
| `500` after pulling new code | Model changed; drop the tables (§8) |
| Voice upload returns `422 … ffmpeg is not installed` | Client sent a non-WAV file. Install ffmpeg or send 16 kHz mono WAV |
| `audio_url` does not load on a phone | `PUBLIC_BASE_URL` still says `localhost`. Set it to an address the phone can reach |
| Browser says `blocked by CORS policy` | Add the dashboard's origin to `CORS_ORIGINS` and restart |
| Bill upload returns `422 unreadable` | Document AI could not find the invoice number, date, total or supplier. Retake a clearer photo |
| Replies feel slow | Check `trace.steps`. Normal: ~1 s per model call. Identical repeats are cached and return instantly |
| WhatsApp webhook returns `403` / `503` | See the [WhatsApp guide](04-whatsapp-integration.md) troubleshooting table |
