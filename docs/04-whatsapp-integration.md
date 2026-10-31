# WhatsApp integration guide

How the WhatsApp bot works, how to connect it to Meta's WhatsApp Cloud API, how to test it, and what to do when it
misbehaves. The bot is the merchant's **capture** channel: forward a bill photo or PDF, send a voice note, or just type.

Prerequisite: the backend is running ([setup guide](01-backend-setup.md)).

## 1. What the bot does

| The merchant sends | The bot does |
|---|---|
| A bill **photo** or **PDF** | Reads it, validates it, checks for duplicates, replies with a summary card and buttons |
| A **voice note** ("Sharma ko paanch hazaar cash diye") | Transcribes it, answers or logs the entry, replies in text and as a voice note |
| **Text** ("Is hafte kitna dena hai?") | The agent answers using the merchant's own ledger |
| A **button tap** | Resumes the pending decision (confirm / discard / ask supplier / pay) |

Everything goes through the same agent and services as the app and web dashboard, so an answer is identical on every channel.

### The core demo conversation (S1)

```
Ramesh:  [photo of the Sharma Traders bill]
Bot:     Bill padh liya ✅
         Sharma Traders · Inv #ST-2291 · 28 Oct
         1 items · ₹18,640 (GST ₹888)
         Due: 4 Nov
         ⚠️ Yeh bill #ST-2291 pehle 12 Oct ko bhi aaya tha aur aapne ₹18,640 pay kar diya hai. Duplicate lag raha hai.
         [Duplicate hai] [Naya bill hai] [Sharma se poochho]
Ramesh:  (taps "Sharma se poochho")
Bot:     Supplier ko message bhej diya. Jawab aate hi bataunga.
Vikas:   Ramesh General Store ne bill #ST-2291 par sawaal poocha hai   [Duplicate hai] [Naya bill hai]
Vikas:   (taps "Duplicate hai")
Ramesh:  Supplier ne bataya: yeh bill duplicate hai. Maine ledger se hata diya.
```

### Things you can say

There is no menu; the agent understands free text in Hindi, English, Hinglish and Devanagari. Phrases the safety-net
router also recognises:

| Say | Result |
|---|---|
| "Is hafte kitna dena hai?" / "What do I owe this week?" | Dues by supplier with a total |
| "Sharma ka hisaab" | That supplier's balance and open issues |
| "Paise kab kam padenge?" | Cash forecast and the shortfall day |
| "Mujhe restock ke liye paise chahiye" | Credit offer preview (consent and acceptance happen in the app) |
| "mera score kitna hai" | Hisaab Score and top reasons |
| "koi alert hai?" | Open alerts |
| "Agarwal dairy ko teen hazaar cash diye" | Logs a **pending** cash entry and asks you to confirm |
| "Sharma ko 42300 pay kar do" | Prepares a payment **draft** and asks you to confirm. It is never sent without the tap |
| "mere paas 40000 cash hai" | Records today's balance; the cash forecast starts from it |
| "CA ke liye report bhejo" | Purchase register link (CSV) |
| (Neha) "IMS mein kya karna hai" | IMS accept / reject / pending suggestions |
| (Vikas) "kaun kitna dena hai", "reminder bhejo" | Receivables, and drafted reminders (not sent until asked) |

## 2. Meta setup (WhatsApp Cloud API test number)

Every Cloud API app gets a free **test number** that can message up to **5 allowlisted recipient numbers**. That is enough for
three team phones plus two spares for judges.

1. Create an app at <https://developers.facebook.com/apps> (type **Business**) and add the **WhatsApp** product.
2. In **WhatsApp → API Setup** note:
   - the **Phone number ID** (of the test number) → `WHATSAPP_PHONE_NUMBER_ID`
   - a **temporary access token** → `WHATSAPP_ACCESS_TOKEN` (**expires after 24 hours**; for a longer run create a System User
     token in Business Settings)
3. Add your recipients under **To** (up to 5) and verify each with the code WhatsApp sends.
4. Get the **App secret** from **App settings → Basic** → `WHATSAPP_APP_SECRET`.
5. Pick any string for `WHATSAPP_VERIFY_TOKEN` (default `hisaab-verify`).
6. Expose the backend over **HTTPS** (Meta will not call `http://`):
   ```bash
   cloudflared tunnel --url http://localhost:8000      # or: ngrok http 8000
   ```
7. In **WhatsApp → Configuration** set the **Callback URL** to `https://<your-tunnel>/webhooks/whatsapp` and the **Verify token**
   to your `WHATSAPP_VERIFY_TOKEN`, click **Verify and save**, then **subscribe to the `messages` field**.
8. Put the values in `.env` and restart the backend:
   ```
   WHATSAPP_ACCESS_TOKEN=EAAG...
   WHATSAPP_PHONE_NUMBER_ID=1234567890
   WHATSAPP_APP_SECRET=abcdef...
   WHATSAPP_VERIFY_TOKEN=hisaab-verify
   PUBLIC_BASE_URL=https://<your-tunnel>
   ```

### Map real phones to the personas

The bot recognises a sender by comparing the **last 10 digits** of their number with `merchants.phone`. The seed uses fake
numbers (Ramesh `9810000001`, Neha `9810000002`, Vikas `9810000003`), so point the personas at your team's phones:

```bash
docker compose exec db psql -U hisaab -c "update merchants set phone='98XXXXXXXX' where id=1;"   # Ramesh
docker compose exec db psql -U hisaab -c "update merchants set phone='97XXXXXXXX' where id=3;"   # Vikas
```

`make reset` re-seeds and restores the fake numbers, so run the `update` again afterwards. A number that matches no merchant
gets "Yeh number Hisaab par registered nahi hai."

## 3. How a message flows

```
 Meta ──POST /webhooks/whatsapp──► verify X-Hub-Signature-256 ──► parse ──► 200 {"received": n}   (fast, so Meta does not retry)
                                                                    │
                                                          background task, one per message
                                                                    ▼
   find merchant by phone ─► text   → agent ─────────────► reply (+ confirmation buttons if something needs a tap)
                             image/pdf → download → read bill → validate → card + buttons
                             voice  → download → convert → speech-to-text → agent → text reply + voice note
                             button → resume the pending decision → reply
```

- **Responses are sent after the 200.** Reading a bill can take several seconds; Meta only waits briefly for the 200.
- **Retries are ignored.** Meta redelivers on slow responses; each message id is processed once (kept in memory per process).
- Every inbound and outbound message is stored in the `messages` table (`channel = 'whatsapp'`), with the agent's trace.

### Buttons and pending decisions

Anything that needs a yes/no is one mechanism: the bot sends buttons whose ids look like `g:<thread>:<choice>`, and the tap
resumes that decision.

| Situation | Buttons (title → choice) |
|---|---|
| Normal bill | Haan, sahi hai → `ok` · Nahi, hata do → `no` |
| Duplicate bill | Duplicate hai → `ignore` · Naya bill hai → `new` · *<Supplier>* se poochho → `ask` |
| Pending cash entry | Haan, sahi hai → `ok` · Nahi → `no` |
| Payment draft | Pay karein → `ok` · Cancel → `no` |

Safety properties: a **second tap does nothing** ("Yeh pehle hi ho chuka hai."); only the **owner** can answer; a decision left
unanswered for **24 hours** expires; pending decisions are stored in Postgres, so they **survive a server restart**.
WhatsApp limits: at most 3 buttons, titles ≤ 20 characters, body ≤ 1,024 characters (the client truncates).

The supplier's reply buttons ("Duplicate hai" / "Naya bill hai" sent to Vikas) use the older stateless ids `qa:<query_id>:duplicate|new_bill`.

## 4. Testing without Meta in the loop

`scripts/send_test_webhook.py` sends a correctly signed webhook to your server.

```bash
# .env must have WHATSAPP_APP_SECRET set, plus any non-empty WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID
uv run python -m scripts.send_test_webhook --url http://localhost:8000/webhooks/whatsapp --text "Is hafte kitna dena hai?"
uv run python -m scripts.send_test_webhook --button g:c-1a2b3c4d5e6f:ignore
uv run python -m scripts.send_test_webhook --phone 919810000003 --text "kaun kitna dena hai"
```

With placeholder credentials the *outbound* send to Meta fails (it is logged and swallowed), but the whole pipeline still runs and
the reply is recorded, so you can read what the bot would have said:

```bash
docker compose exec db psql -U hisaab -c \
  "select direction, left(text,100) as text, trace_json->>'source' as path from messages where channel='whatsapp' order by id desc limit 6"
```

For automated checks, `tests/test_whatsapp.py` and `tests/test_engines_end_to_end.py` drive the full dispatcher with a fake
WhatsApp client (no network).

## 5. Voice notes

- WhatsApp voice notes are **OGG/Opus**, so the server needs **`ffmpeg`** to convert them to WAV for speech-to-text. Without it
  the bot replies "Abhi yeh nahi ho paya…". Install it: `sudo apt install ffmpeg`.
- The spoken reply is generated as WAV and **converted to OGG/Opus** (also via `ffmpeg`) before it is uploaded and sent as audio.
  If conversion or upload fails, the **text reply has already been delivered**; only the voice note is skipped.
- Replies are kept to about two sentences, with long numbers left in the text.

## 6. Proactive messages (due-date reminders and the weekly digest)

Two messages are sent without the merchant asking:

- **Bill due tomorrow**: *"Sharma Traders ka bill kal due hai, ₹42,300 (ST-2302)."* One message per supplier, plus a matching
  **Soundbox announcement** in the app (`GET /merchants/{id}/events`).
- **Weekly payables digest** (Mondays): the same breakdown as asking "Is hafte kitna dena hai?", once per ISO week, only if something is owed.

They are sent by a small background scheduler, off by default:

```
SCHEDULER_ENABLED=true     # start the loop with the server
SCHEDULER_INTERVAL_S=900   # how often it looks (every 15 minutes)
SCHEDULER_HOUR=9           # daily jobs wait until this local hour
```

Every send is recorded (table `notification_log`), so running the loop often, or running a job by hand, never messages anyone twice.
To try them on demand, pretend it is the day before a due date:

```bash
curl -X POST 'localhost:8000/demo/run-due-reminders?on=2026-11-03'   # Sharma's ST-2302 is due 4 Nov
curl -X POST 'localhost:8000/demo/run-weekly-digest?on=2026-11-02'   # Monday
```

Both are subject to the 24-hour rule below.

## 6b. The 24-hour window (important for reminders)

WhatsApp only allows free-form messages within **24 hours of the user's last message**. Outside it, only **pre-approved
templates** are allowed.

- Everything the bot sends in reply to a user is inside the window.
- **Proactive** messages (distributor reminders to retailers, "bill due tomorrow", the weekly digest) are free-form text in this build, so they only
  arrive if the recipient messaged the bot in the last 24 hours. **Approved-template sending is not implemented.**
- For the demo: have each demo phone send the bot a message first (any "hi"), and say on the slide that production uses approved
  utility templates.

## 7. Configuration reference

| Variable | Purpose |
|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Graph API bearer token. Both this and the phone number ID must be set or the webhook returns `503` |
| `WHATSAPP_PHONE_NUMBER_ID` | The sending number's ID |
| `WHATSAPP_APP_SECRET` | Used to verify `X-Hub-Signature-256`. **If empty, every webhook is rejected** (fail closed) |
| `WHATSAPP_VERIFY_TOKEN` | Must match what you typed in Meta's webhook form (default `hisaab-verify`) |
| `PUBLIC_BASE_URL` | Your HTTPS tunnel URL (links in replies, such as the CA report, use it) |

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Verify and save" fails in Meta | `WHATSAPP_VERIFY_TOKEN` mismatch, or the tunnel is down. `GET /webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=…&hub.challenge=1` should return `1` |
| Webhook returns `403 Bad signature` | `WHATSAPP_APP_SECRET` is wrong or empty, or a proxy altered the body. Re-copy the secret from App settings → Basic |
| Webhook returns `503 WhatsApp is not configured` | Set both `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` and restart |
| Nothing arrives at the server | Not subscribed to the `messages` field, or the sender is not on the allowlist |
| Messages arrive, no replies reach the phone | Access token expired (24 h for temporary tokens), or the recipient is not allowlisted (Meta error `131030`). Check the server log for `WhatsApp send … failed` |
| "Yeh number Hisaab par registered nahi hai." | The sender's last 10 digits do not match `merchants.phone`. See §2 |
| Voice notes get "Abhi yeh nahi ho paya" | `ffmpeg` is not installed |
| Bill photo gets "Could not read the bill (…)" | Document AI could not find the invoice number, date, total or supplier. Retake the photo |
| A tap says "Yeh request purani ho gayi hai" | The decision is older than 24 hours. Send the bill / request again |
| `**bold**` shows as literal asterisks | WhatsApp bold is `*bold*`. The model sometimes uses Markdown double asterisks. Cosmetic; the facts are unaffected |
| Replies are slow | Reading a bill takes a few seconds (Document AI job). Text questions take about 1 s. Check `trace_json` in `messages` |

## 9. Known limits

- **No Twilio fallback.** Only the Meta Cloud API is implemented. The sending side is behind a small interface
  (`app/channels/base.py`, `app/channels/whatsapp/client.py`), which is where a Twilio adapter would plug in.
- **No template messages** (see §6) and no list messages; replies use text and up to three reply buttons.
- **Dedupe and background work are in-process.** Fine for one server; a multi-instance deployment would need a shared store and a queue.
- **Where the code is:** `app/api/routers/webhooks.py` (endpoint), `app/channels/whatsapp/` (signature, payload parser, Graph client,
  notifier, dispatcher, bill cards, button actions), `app/ai/graph/confirmations.py` (pending decisions).
