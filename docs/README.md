# Hisaab Agent: integration guides

| Guide | Read it if you are… |
|---|---|
| [01 · Backend setup](01-backend-setup.md) | running the server, configuring `.env`, seeding/resetting demo data, running tests and evals, preparing the stage demo |
| [02 · Web integration + full API reference](02-web-integration.md) | building the distributor dashboard, or looking up **any** endpoint (all 54 are documented with real examples) |
| [03 · Android integration](03-android-integration.md) | building the merchant app: networking, models, every screen's calls, camera scan, voice / Soundbox mode |
| [04 · WhatsApp integration](04-whatsapp-integration.md) | connecting Meta's WhatsApp Cloud API, testing the bot, troubleshooting |

**Start here:** [01](01-backend-setup.md). Everything else assumes the backend is running.

## Five facts that apply everywhere

1. **There is no login.** Clients pick a merchant id: `1` Ramesh (retailer), `2` Neha (wholesaler), `3` Vikas (distributor).
2. **The AI never moves money.** The agent can only *draft* a payment; a person confirms it with a separate call or button tap.
3. **Money is plain INR numbers**; "today" is pinned to `2026-10-31` for the demo.
4. **Errors** are `{"error": "<code>", "message": "…"}` (validation errors use FastAPI's `{"detail": […]}`).
5. **The contract** is `shared/openapi.json` (`make openapi`), also served live at `/openapi.json` and `/docs`.
